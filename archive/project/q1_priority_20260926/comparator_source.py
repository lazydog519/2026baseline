"""Read prior official component-packing results as a comparison only.

No solver imports or calls this module. It never influences policy selection.
"""
import argparse
import csv
import gzip
import json
from pathlib import Path

from baseline import make_plan


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, required=True)
    a = ap.parse_args()
    project = a.project.resolve()
    ref = {}
    with (project/'final_metrics/per_case_metrics.csv').open(encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            if row['cores'] == '5':
                ref[row['case']] = int(float(row['q1_cycles']))
    rows = []
    for i in range(1, 101):
        case = f'case_{i:03d}'
        graph = json.loads((project/'official/data'/f'{case}.json').read_text(encoding='utf-8'))
        expected = make_plan(graph, 5)
        found = []
        for result_path in project.glob(f'baseline_results*/{case}/q1_n5/result.json.gz'):
            plan_path = result_path.with_name(f'{case}_multicore_res.json')
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            if plan != expected:
                raise ValueError(f'comparator plan differs from fresh component packing: {plan_path}')
            with gzip.open(result_path, 'rt', encoding='utf-8') as stream:
                result = json.load(stream)
            if result['makespan'] != ref[case]:
                raise ValueError(f'comparator official result conflicts with prior table: {result_path}')
            found.append((result['makespan'], result['data_movement_bytes']['added_copy_bytes']))
        if not found or len(set(found)) != 1:
            raise ValueError(f'comparator missing or contradictory: {case}')
        cycles, added = found[0]
        rows.append(dict(case=case, cores=5, component_cycles=cycles,
                         component_added_copy_bytes=added))
    target = Path(__file__).resolve().parent/'component_comparator.csv'
    with target.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f'verified {len(rows)} graphs; source is a reporting comparator, not a solver input')


if __name__ == '__main__':
    main()
