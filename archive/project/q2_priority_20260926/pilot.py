"""Small development experiment. The official evaluator is used here only.

This file is never packaged with the frozen graph-only inference solver.
"""
import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--cases', nargs='+', default=['case_001', 'case_002', 'case_010', 'case_015'])
    ap.add_argument('--cores', type=int, default=5)
    args = ap.parse_args()
    project = args.project.resolve()
    sys.path.insert(0, str(project/'solution'))
    sys.path.insert(0, str(project/'official/code'))
    from q2_cold import Problem
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config
    from stub_multicore_cut_and_schedule import derive_multicore_plan

    config = project/'official/data/config.txt'
    fixed = read_evaluation_config(str(config))
    delay = read_scene_b_config(str(config))['cross_core_copy_delay_cycles']
    output = Path(__file__).with_name('pilot.csv')
    fields = ['case', 'cores', 'candidate', 'status', 'proxy_cycles', 'proxy_ddr_bytes',
              'makespan_cycles', 'added_copy_bytes', 'spill_bytes', 'seconds', 'error']
    done = set()
    if output.exists():
        with output.open(encoding='utf-8', newline='') as stream:
            done = {(row['case'], int(row['cores']), row['candidate']) for row in csv.DictReader(stream)}
    with output.open('a', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if not output.stat().st_size:
            writer.writeheader()
        for case in args.cases:
            graph = json.loads((project/'official/data'/f'{case}.json').read_text(encoding='utf-8'))
            problem = Problem(graph, args.cores, fixed['bandwidth'], delay, fixed['capacity'])
            width = problem.initial_width
            descriptors = [('base', 0, args.cores), ('valley', width, args.cores),
                           ('valley', 2*width, args.cores), ('data', width, args.cores),
                           ('data', 2*width, args.cores), ('band', width, args.cores)]
            for descriptor in descriptors:
                name = '%s_w%d_k%d' % descriptor
                if (case, args.cores, name) in done:
                    continue
                start = time.perf_counter()
                row = dict(case=case, cores=args.cores, candidate=name)
                try:
                    plan = problem.construct(descriptor)
                    derive_multicore_plan(graph, plan)
                    proxy, traffic, _ = problem.estimate(plan)
                    row.update(proxy_cycles=proxy, proxy_ddr_bytes=traffic)
                    result = evaluate_scene_b(graph, plan, bandwidth=fixed['bandwidth'],
                                              capacity=fixed['capacity'], cross_core_copy_delay=delay)
                    move = result['data_movement_bytes']
                    if move['scheduled_copy_bytes'] - move['spill_added_copy_bytes'] != traffic:
                        raise ValueError('pre-spill DDR accounting mismatch')
                    row.update(status='ok', makespan_cycles=result['makespan'],
                               added_copy_bytes=move['added_copy_bytes'],
                               spill_bytes=move['spill_added_copy_bytes'])
                except Exception as exc:
                    row.update(status='error', error=repr(exc))
                row['seconds'] = time.perf_counter()-start
                writer.writerow(row)
                stream.flush()
                print(case, name, row['status'], row.get('makespan_cycles'), flush=True)


if __name__ == '__main__':
    main()
