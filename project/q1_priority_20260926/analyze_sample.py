"""Describe pre-frozen development/holdout labels; never used by solver.py."""
import csv
import json
import statistics
from pathlib import Path

from solver import choose


def main():
    root = Path(__file__).resolve().parent
    policy = json.loads((root/'policy.json').read_text(encoding='utf-8'))
    result = {}
    allrows = []
    for scope in ('development', 'holdout'):
        labels = [json.loads(line) for line in (root/scope/'labels.jsonl').read_text(encoding='utf-8').splitlines()]
        groups = {}
        for row in labels:
            groups.setdefault((row['case'], row['cores']), {})[row['candidate_sha256']] = row
        pairs = []
        for frozen in sorted((root/scope).glob('case_*_n5.json')):
            item = json.loads(frozen.read_text(encoding='utf-8'))
            ref = groups[item['case'], item['cores']]
            selected = choose(item['candidates'], policy)
            base = next(r for r in item['candidates'] if r['name'] == 'component_vector')
            chosen = ref[selected['fingerprint']]
            baseline = ref[base['fingerprint']]
            oracle = min(ref.values(), key=lambda r: r['cycles'] if r['status']=='ok' else float('inf'))
            pairs.append(dict(scope=scope, case=item['case'], cores=item['cores'],
                              selected=chosen['candidate'], selected_cycles=chosen['cycles'],
                              component_cycles=baseline['cycles'], oracle_cycles=oracle['cycles'],
                              selected_added_copy_bytes=chosen['added_copy_bytes'],
                              component_added_copy_bytes=baseline['added_copy_bytes'],
                              selected_boundary_bytes=selected['boundary_bytes'],
                              selected_proxy_cycles=selected['proxy_cycles'],
                              ratio=chosen['cycles']/baseline['cycles']))
        allrows.extend(pairs)
        result[scope] = dict(cases=len(pairs), official_candidate_labels=len(labels),
                             errors=sum(r['status']!='ok' for r in labels),
                             improved=sum(r['ratio'] < 0.999999 for r in pairs),
                             worsened=sum(r['ratio'] > 1.000001 for r in pairs),
                             mean_relative_makespan_change=statistics.mean(r['ratio']-1 for r in pairs),
                             cases_detail=pairs)
    with (root/'sample_metrics.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(allrows[0]))
        writer.writeheader()
        writer.writerows(allrows)
    (root/'sample_summary.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:{x:v for x,v in s.items() if x!='cases_detail'} for k,s in result.items()},indent=2))


if __name__ == '__main__':
    main()
