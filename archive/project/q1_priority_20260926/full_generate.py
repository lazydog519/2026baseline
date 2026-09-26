"""Generate each official graph/core plan in a separate evaluator-free process."""
import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    root = Path(__file__).resolve().parent
    project = a.project.resolve()
    output = root / 'full_plans'
    output.mkdir(exist_ok=True)
    scripts = ('solver.py', 'mechanistic.py', 'q1_optimized.py', 'baseline.py', 'policy.json')
    source_hashes = {name: sha(root/name) for name in scripts}
    cfg = project/'official/data/config.txt'

    def job(i, n):
        case = f'case_{i:03d}'
        graph = project/'official/data'/f'{case}.json'
        target = output/f'{case}_n{n}.json'
        report = output/f'{case}_n{n}_generation.json'
        cmd = [sys.executable, '-X', 'utf8', str(root/'solver.py'), str(graph),
               '-n', str(n), '--config', str(cfg), '-o', str(target),
               '--policy', str(root/'policy.json'), '--report', str(report)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return dict(case=case, cores=n, exit_code=result.returncode,
                    error=result.stderr[-1000:], graph_sha256=sha(graph),
                    plan_sha256=sha(target) if result.returncode == 0 else None,
                    report_sha256=sha(report) if result.returncode == 0 else None)

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(job, i, n) for i in range(1, 101) for n in (2, 3, 4, 5)]
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            rows.append(row)
            print(row['case'], row['cores'], row['exit_code'], flush=True)
    rows.sort(key=lambda x: (x['case'], x['cores']))
    manifest = dict(scope='100 official graphs x cores 2-5', evaluator_imported=False,
                    generation_mode='one fresh process per graph/core; no historical plan or score input',
                    source_sha256=source_hashes, config_sha256=sha(cfg), jobs=rows)
    (root/'full_generation_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    if any(r['exit_code'] for r in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
