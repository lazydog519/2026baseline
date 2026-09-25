"""Input-only cache descriptors and a small, cost-bounded pilot selection."""
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

P=Path(__file__).resolve().parents[1]


def main():
    prior={r['case']:r for r in csv.DictReader((P/'q1_cold/input_profiles.csv').open(encoding='utf-8'))}
    rows=[]
    for f in sorted((P/'official/data').glob('case_*.json')):
        raw=f.read_bytes();g=json.loads(raw);old=prior[f.stem]
        assert hashlib.sha256(raw).hexdigest()==old['input_sha256']
        ops={o['id'] for o in g['ops'] if o['op'] not in ('COPY_IN','COPY_OUT')}
        prod,cons=defaultdict(set),defaultdict(set)
        for e in g['edges']:
            if e['source'] in ops:prod[e['target']].add(e['source'])
            if e['target'] in ops:cons[e['source']].add(e['target'])
        inputs=[t for t in g['tensors'] if cons[t['id']] and not prod[t['id']]]
        shared=[t for t in inputs if len(cons[t['id']])>1]
        rows.append(dict(case=f.stem,input_sha256=old['input_sha256'],compute_ops=int(old['compute_ops']),
            depth=int(old['depth']),weak_components=int(old['weak_components']),
            structural_parallelism=float(old['structural_parallelism']),
            input_bytes=sum(t['size'] for t in inputs),shared_input_bytes=sum(t['size'] for t in shared),
            shared_input_count=len(shared),max_input_consumers=max((len(cons[t['id']]) for t in inputs),default=0),
            potential_repeated_input_bytes=sum(t['size']*(len(cons[t['id']])-1) for t in inputs),
            input_working_set_in_l2_capacities=sum(t['size'] for t in inputs)/1048576))
    out=Path(__file__).parent
    with (out/'input_cache_profiles.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    pool=[r for r in rows if r['compute_ops']<=5000]
    fields=['compute_ops','depth','weak_components','structural_parallelism','shared_input_bytes','max_input_consumers','input_working_set_in_l2_capacities']
    values=[[math.log1p(r[k]) for k in fields] for r in pool]
    lo=[min(v[j] for v in values) for j in range(len(fields))];hi=[max(v[j] for v in values) for j in range(len(fields))]
    values=[[(v[j]-lo[j])/max(1e-12,hi[j]-lo[j]) for j in range(len(fields))] for v in values]
    centre=[statistics.median(v[j] for v in values) for j in range(len(fields))]
    dist=lambda a,b:sum((x-y)**2 for x,y in zip(a,b))
    chosen=[min(range(len(pool)),key=lambda i:(dist(values[i],centre),pool[i]['case']))]
    while len(chosen)<6:
        chosen.append(max((i for i in range(len(pool)) if i not in chosen),key=lambda i:(min(dist(values[i],values[j]) for j in chosen),-i)))
    spec=dict(version='q3-pilot-selection-v1',all_profiled_cases=len(rows),eligible_pilot_cases=len(pool),
        selection='log1p/min-max/farthest-point; actual input descriptors only; no measured scores',
        max_compute_ops_for_pilot=5000,fields=fields,cores=[1,2,5],
        development=[pool[i]['case'] for i in chosen[::2]],confirmation=[pool[i]['case'] for i in chosen[1::2]],
        limitations='Cost-bounded small-case feasibility study, not a representative 100-case average or unseen generalisation test.',
        parameter_source='Fixed exploratory budget; no statistical tuning claim.',
        feature_warning='Potential repeated bytes count per-op consumers before assignment; not a bound or a measured DDR volume.')
    (out/'pilot_selection.json').write_text(json.dumps(spec,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(spec))


if __name__=='__main__':main()
