"""Development-only: run fresh pure inference, then evaluate its frozen plan."""
import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--cases', nargs='+', required=True)
    ap.add_argument('--cores', nargs='+', type=int, default=[5])
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    project = args.project.resolve()
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project/'official/code'))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config

    config = project/'official/data/config.txt'
    fixed = read_evaluation_config(str(config))
    delay = read_scene_b_config(str(config))['cross_core_copy_delay_cycles']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    jobs = args.output.with_suffix('')
    jobs.mkdir(parents=True, exist_ok=True)
    fields = ('case', 'cores', 'selected', 'status', 'makespan_cycles', 'added_copy_bytes',
              'spill_bytes', 'inference_seconds', 'evaluation_seconds', 'error')
    done = set()
    if args.output.exists():
        with args.output.open(encoding='utf-8', newline='') as stream:
            done = {(r['case'], int(r['cores'])) for r in csv.DictReader(stream) if r['status']=='ok'}
    with args.output.open('a', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        if not args.output.stat().st_size:
            writer.writeheader()
        for case in args.cases:
            graph_path = project/'official/data'/f'{case}.json'
            for cores in args.cores:
                if (case, cores) in done:
                    continue
                plan_path, report_path = jobs/f'{case}_n{cores}.json', jobs/f'{case}_n{cores}_report.json'
                row = dict(case=case, cores=cores)
                try:
                    subprocess.run([sys.executable, str(root/'solver.py'), str(graph_path),
                                    '-n', str(cores), '--config', str(config), '-o', str(plan_path),
                                    '--report', str(report_path)], check=True,
                                   capture_output=True, text=True, encoding='utf-8',
                                   errors='replace', timeout=180)
                    report = json.loads(report_path.read_text(encoding='utf-8'))
                    row.update(selected=report['selected'], inference_seconds=report['inference_seconds'])
                    start = time.perf_counter()
                    graph = json.loads(graph_path.read_text(encoding='utf-8'))
                    plan = json.loads(plan_path.read_text(encoding='utf-8'))
                    result = evaluate_scene_b(graph, plan, bandwidth=fixed['bandwidth'],
                                              capacity=fixed['capacity'], cross_core_copy_delay=delay)
                    movement = result['data_movement_bytes']
                    row.update(status='ok', makespan_cycles=result['makespan'],
                               added_copy_bytes=movement['added_copy_bytes'],
                               spill_bytes=movement['spill_added_copy_bytes'],
                               evaluation_seconds=time.perf_counter()-start)
                except Exception as exc:
                    row.update(status='error', error=repr(exc))
                writer.writerow(row)
                stream.flush()
                print(case, cores, row['status'], row.get('selected'),
                      row.get('makespan_cycles'), flush=True)


if __name__ == '__main__':
    main()
