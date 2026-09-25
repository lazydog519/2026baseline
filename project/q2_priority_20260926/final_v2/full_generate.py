"""Freeze Scene-B plans produced by independent graph-only subprocesses."""
import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SOURCES = ('solver.py', 'model.py', 'memory_proxy.py', 'q1_optimized.py', 'baseline.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--cores', nargs='+', type=int, default=[2, 3, 4, 5])
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--resume', action='store_true')
    args = ap.parse_args()
    if not set(args.cores) <= {2, 3, 4, 5}:
        raise ValueError('cores must be 2–5')
    project, root = args.project.resolve(), Path(__file__).resolve().parent
    output = root/'full_plans'
    output.mkdir(exist_ok=True)
    cfg = project/'official/data/config.txt'
    source_hash = {name: sha(root/name) for name in SOURCES}
    manifest_path = root/'full_generation_manifest.json'
    if manifest_path.exists():
        if not args.resume:
            raise FileExistsError('generation manifest exists; use --resume')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['source_sha256'] != source_hash or manifest['config_sha256'] != sha(cfg):
            raise ValueError('frozen source or config changed')
    else:
        manifest = dict(scope='100 official graphs, cores 2–5', evaluator_imported=False,
                        generation_mode='fresh process for each graph/core, graph and fixed config only',
                        source_sha256=source_hash, config_sha256=sha(cfg), jobs=[])
    rows = {(r['case'], r['cores']): r for r in manifest['jobs']}

    def job(case, cores):
        graph = project/'official/data'/f'{case}.json'
        target = output/f'{case}_n{cores}.json'
        report = output/f'{case}_n{cores}_generation.json'
        result = subprocess.run([sys.executable, '-X', 'utf8', str(root/'solver.py'),
                                 str(graph), '-n', str(cores), '--config', str(cfg),
                                 '-o', str(target), '--report', str(report)],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=180)
        return dict(case=case, cores=cores, exit_code=result.returncode,
                    error=result.stderr[-1000:], graph_sha256=sha(graph),
                    plan_sha256=sha(target) if result.returncode == 0 else None,
                    report_sha256=sha(report) if result.returncode == 0 else None)

    todo = []
    for i in range(1, 101):
        case = f'case_{i:03d}'
        for cores in args.cores:
            prior = rows.get((case, cores))
            graph = project/'official/data'/f'{case}.json'
            target = output/f'{case}_n{cores}.json'
            report = output/f'{case}_n{cores}_generation.json'
            if prior and prior['exit_code'] == 0 and all((
                prior['graph_sha256'] == sha(graph), target.exists(), report.exists(),
                prior['plan_sha256'] == sha(target) if target.exists() else False,
                prior['report_sha256'] == sha(report) if report.exists() else False)):
                continue
            todo.append((case, cores))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {pool.submit(job, *key): key for key in todo}
        for future in concurrent.futures.as_completed(future_map):
            key = future_map[future]
            try:
                row = future.result()
            except Exception as exc:
                row = dict(case=key[0], cores=key[1], exit_code=1, error=repr(exc))
            rows[key] = row
            manifest['jobs'] = [rows[k] for k in sorted(rows)]
            manifest_path.write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
            print(*key, row['exit_code'], flush=True)
    if any(rows[(f'case_{i:03d}', n)]['exit_code'] for i in range(1, 101) for n in args.cores):
        raise SystemExit('generation failed')


if __name__ == '__main__':
    main()
