"""Post-freeze official acceptance of independently generated Scene-A plans."""
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


def score(project, manifest_row):
    sys.path.insert(0, str(project/'official/code'))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_1 import evaluate_scene_a, read_scene_a_config
    name, n = manifest_row['case'], manifest_row['cores']
    graph_path = project/'official/data'/f'{name}.json'
    plan_path = Path(__file__).resolve().parent/'full_plans'/f'{name}_n{n}.json'
    report_path = plan_path.with_name(plan_path.stem+'_generation.json')
    if sha(graph_path) != manifest_row['graph_sha256'] or sha(plan_path) != manifest_row['plan_sha256'] or sha(report_path) != manifest_row['report_sha256']:
        raise ValueError(f'frozen input/plan/report changed: {name} n{n}')
    graph = json.loads(graph_path.read_text(encoding='utf-8'))
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    config = project/'official/data/config.txt'
    cfg, scene = read_evaluation_config(str(config)), read_scene_a_config(str(config))
    start = time.perf_counter()
    result = evaluate_scene_a(graph, plan, bandwidth=cfg['bandwidth'], capacity=cfg['capacity'],
                              same_core_wait=scene['task_same_core_wait_cycles'],
                              cross_core_wait=scene['task_cross_core_wait_cycles'])
    return dict(case=name, cores=n, status='ok', makespan_cycles=result['makespan'],
                added_copy_bytes=result['data_movement_bytes']['added_copy_bytes'],
                scheduled_copy_bytes=result['data_movement_bytes']['scheduled_copy_bytes'],
                spill_added_copy_bytes=result['data_movement_bytes']['spill_added_copy_bytes'],
                plan_sha256=manifest_row['plan_sha256'], seconds=time.perf_counter()-start)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()
    project = a.project.resolve()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root/'full_generation_manifest.json').read_text(encoding='utf-8'))
    if len(manifest['jobs']) != 400 or any(row['exit_code'] for row in manifest['jobs']):
        raise ValueError('generation incomplete')
    for name, expected in manifest['source_sha256'].items():
        if sha(root/name) != expected:
            raise ValueError(f'frozen solver source changed: {name}')
    if sha(project/'official/data/config.txt') != manifest['config_sha256']:
        raise ValueError('fixed hardware config changed')
    progress = root/'full_audit_progress.csv'
    fields = ('case', 'cores', 'status', 'makespan_cycles', 'added_copy_bytes',
              'scheduled_copy_bytes', 'spill_added_copy_bytes', 'plan_sha256', 'seconds', 'error')
    rows = {}
    if a.resume and progress.exists():
        for row in csv.DictReader(progress.open(encoding='utf-8')):
            if row['status'] == 'ok':
                rows[row['case'], int(row['cores'])] = row
    elif progress.exists():
        raise FileExistsError('audit already started; use --resume')
    jobs = [r for r in manifest['jobs'] if (r['case'], r['cores']) not in rows]
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        future_to_row = {pool.submit(score, project, r): r for r in jobs}
        for future in concurrent.futures.as_completed(future_to_row):
            job = future_to_row[future]
            try:
                row = future.result()
            except Exception as exc:
                row = dict(case=job['case'], cores=job['cores'], status='error', error=repr(exc))
            rows[row['case'], row['cores']] = row
            with progress.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows({k:r.get(k, '') for k in fields} for r in
                                 (rows[key] for key in sorted(rows)))
            print(row['case'], row['cores'], row['status'], row.get('makespan_cycles'), flush=True)
    if len(rows) != 400 or any(r['status'] != 'ok' for r in rows.values()):
        raise SystemExit('official acceptance incomplete or failed')
    reference = {}
    with (project/'final_metrics/per_case_metrics.csv').open(encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            value = float(row['singlecore_cycles'])
            if row['case'] in reference and reference[row['case']] != value:
                raise ValueError('single-core reference differs across core counts')
            reference[row['case']] = value
    if len(reference) != 100:
        raise ValueError('single-core reference missing cases')
    numeric = []
    for row in rows.values():
        row['speedup'] = reference[row['case']] / float(row['makespan_cycles'])
        numeric.append(row)
    with (root/'full_metrics.csv').open('w', encoding='utf-8', newline='') as stream:
        outfields = fields + ('speedup',)
        writer = csv.DictWriter(stream, fieldnames=outfields)
        writer.writeheader()
        writer.writerows({k:r.get(k, '') for k in outfields} for r in sorted(numeric,key=lambda x:(x['case'],int(x['cores']))))
    summary = dict(complete_cases=100, jobs=400, failed=0, singlecore_reference='official fixed singlecore cycles from final_metrics/per_case_metrics.csv',
                   mean_speedup_by_cores={str(n):statistics.mean(float(r['speedup']) for r in numeric if int(r['cores'])==n) for n in (2,3,4,5)},
                   mean_added_copy_bytes_by_cores={str(n):statistics.mean(float(r['added_copy_bytes']) for r in numeric if int(r['cores'])==n) for n in (2,3,4,5)},
                   source_sha256=manifest['source_sha256'])
    (root/'full_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
