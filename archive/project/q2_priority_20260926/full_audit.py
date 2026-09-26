"""Post-freeze acceptance with the unchanged official Scene-B evaluator."""
import argparse
import concurrent.futures
import csv
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(project, root, job):
    sys.path.insert(0, str(project/'official/code'))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config
    case, n = job['case'], job['cores']
    graph_path = project/'official/data'/f'{case}.json'
    plan_path = root/'full_plans'/f'{case}_n{n}.json'
    report_path = root/'full_plans'/f'{case}_n{n}_generation.json'
    if (sha(graph_path) != job['graph_sha256'] or sha(plan_path) != job['plan_sha256']
            or sha(report_path) != job['report_sha256']):
        raise ValueError('frozen input or plan changed')
    graph = json.loads(graph_path.read_text(encoding='utf-8'))
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    cfg = project/'official/data/config.txt'
    fixed = read_evaluation_config(str(cfg))
    delay = read_scene_b_config(str(cfg))['cross_core_copy_delay_cycles']
    start = time.perf_counter()
    result = evaluate_scene_b(graph, plan, bandwidth=fixed['bandwidth'],
                              capacity=fixed['capacity'], cross_core_copy_delay=delay)
    movement = result['data_movement_bytes']
    return dict(case=case, cores=n, status='ok', makespan_cycles=result['makespan'],
                added_copy_bytes=movement['added_copy_bytes'],
                scheduled_copy_bytes=movement['scheduled_copy_bytes'],
                spill_added_copy_bytes=movement['spill_added_copy_bytes'],
                plan_sha256=job['plan_sha256'], seconds=time.perf_counter()-start)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--cores', nargs='+', type=int, default=[2, 3, 4, 5])
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--resume', action='store_true')
    args = ap.parse_args()
    project, root = args.project.resolve(), Path(__file__).resolve().parent
    manifest = json.loads((root/'full_generation_manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['source_sha256'].items():
        if sha(root/name) != digest:
            raise ValueError(f'frozen solver source changed: {name}')
    if sha(project/'official/data/config.txt') != manifest['config_sha256']:
        raise ValueError('hardware config changed')
    jobs = [r for r in manifest['jobs'] if r['cores'] in args.cores]
    expected = {(f'case_{i:03d}', n) for i in range(1, 101) for n in args.cores}
    if {(r['case'], r['cores']) for r in jobs} != expected or any(r['exit_code'] for r in jobs):
        raise ValueError('requested generation incomplete')
    path = root/'full_audit_progress.csv'
    fields = ('case', 'cores', 'status', 'makespan_cycles', 'added_copy_bytes',
              'scheduled_copy_bytes', 'spill_added_copy_bytes', 'plan_sha256', 'seconds', 'error')
    rows = {}
    if path.exists():
        if not args.resume:
            raise FileExistsError('audit already started; use --resume')
        with path.open(encoding='utf-8', newline='') as stream:
            rows = {(r['case'], int(r['cores'])): r for r in csv.DictReader(stream)
                    if r['status'] == 'ok'}
    todo = [r for r in jobs if (r['case'], r['cores']) not in rows]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(score, project, root, r): r for r in todo}
        for future in concurrent.futures.as_completed(pending):
            job = pending[future]
            try:
                row = future.result()
            except Exception as exc:
                row = dict(case=job['case'], cores=job['cores'], status='error', error=repr(exc))
            rows[row['case'], int(row['cores'])] = row
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fields)
                writer.writeheader()
                writer.writerows({k:rows[key].get(k, '') for k in fields} for key in sorted(rows))
            print(row['case'], row['cores'], row['status'], row.get('makespan_cycles'), flush=True)
    if any(key not in rows or rows[key]['status'] != 'ok' for key in expected):
        raise SystemExit('official acceptance incomplete')
    reference = {}
    with (project/'final_metrics/per_case_metrics.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            value = float(row['singlecore_cycles'])
            if row['case'] in reference and reference[row['case']] != value:
                raise ValueError('single-core reference mismatch')
            reference[row['case']] = value
    metrics = []
    for row in rows.values():
        row['speedup'] = reference[row['case']]/float(row['makespan_cycles'])
        metrics.append(row)
    with (root/'full_metrics.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fields+('speedup',))
        writer.writeheader()
        writer.writerows({k:r.get(k, '') for k in fields+('speedup',)}
                         for r in sorted(metrics, key=lambda r:(r['case'],int(r['cores']))))
    available = sorted(set(int(r['cores']) for r in metrics))
    summary = dict(complete_cases=100, audited_jobs=len(metrics), expected_jobs=100*len(available),
                   failed=0, mean_speedup_by_cores={str(n):statistics.mean(float(r['speedup'])
                       for r in metrics if int(r['cores']) == n) for n in available},
                   mean_added_copy_bytes_by_cores={str(n):statistics.mean(float(r['added_copy_bytes'])
                       for r in metrics if int(r['cores']) == n) for n in available},
                   source_sha256=manifest['source_sha256'])
    target = root/('full_summary.json' if len(metrics) == 400 else 'partial_summary.json')
    target.write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
