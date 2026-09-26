"""Describe all input DAGs and choose samples without reading any scores."""
import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from q1_optimized import compute_dag, topological_depth


def profile(graph, bandwidth):
    ops, pred, succ = compute_dag(graph)
    order, depth = topological_depth(ops, pred, succ)
    widths = Counter(depth.values())
    parent = {o:o for o in ops}
    def find(o):
        while parent[o] != o:
            parent[o] = parent[parent[o]]
            o = parent[o]
        return o
    critical, work = {}, defaultdict(int)
    for o in order:
        critical[o] = ops[o]['cycles'] + max((critical[x] for x in pred[o]), default=0)
        work[ops[o]['pipe']] += ops[o]['cycles']
        for x in succ[o]:
            a,b = find(o),find(x)
            if a != b: parent[max(a,b)] = min(a,b)
    components = Counter(find(o) for o in ops)
    prod, cons = defaultdict(set), defaultdict(set)
    allops = {o['id']:o for o in graph['ops']}
    for e in graph['edges']:
        if e['source'] in allops: prod[e['target']].add(e['source'])
        if e['target'] in allops: cons[e['source']].add(e['target'])
    copy_bytes = 0
    for t in graph['tensors']:
        copy_bytes += t['size']*(sum(allops[o]['op']=='COPY_IN' for o in prod[t['id']])
                                +sum(allops[o]['op']=='COPY_OUT' for o in cons[t['id']]))
    total = sum(work.values())
    cp = max(critical.values(),default=0)
    feature = dict(compute_ops=len(ops),tensor_count=len(graph['tensors']),edges=len(graph['edges']),
                   depth=max(depth.values(),default=0),width_max=max(widths.values(),default=0),
                   weak_components=len(components),largest_component_fraction=max(components.values(),default=0)/max(1,len(ops)),
                   branches=sum(len(succ[o])>1 for o in ops),joins=sum(len(pred[o])>1 for o in ops),
                   compute_cycles=total,critical_path_cycles=cp,
                   structural_parallelism=total/max(1,cp),
                   original_copy_bytes=copy_bytes,io_compute_ratio=(copy_bytes/bandwidth)/max(1,total),
                   m_share=work['PIPE_M']/max(1,total),
                   max_l1_tensor_bytes=max((t['size'] for t in graph['tensors'] if t['pos']=='L1'),default=0),
                   max_ub_tensor_bytes=max((t['size'] for t in graph['tensors'] if t['pos']=='UB'),default=0),
                   max_compute_producers_per_tensor=max((len(v & ops.keys()) for v in prod.values()),default=0))
    return feature


def select_samples(rows, count=20):
    # Deterministic farthest-point coverage of input descriptors, not result ranking.
    fields = ['compute_ops','depth','weak_components','structural_parallelism','io_compute_ratio','width_max','joins']
    vals = [[math.log1p(r[k]) for k in fields] for r in rows]
    lo = [min(v[j] for v in vals) for j in range(len(fields))]
    hi = [max(v[j] for v in vals) for j in range(len(fields))]
    vals = [[(v[j]-lo[j])/max(1e-12,hi[j]-lo[j]) for j in range(len(fields))] for v in vals]
    centre = [statistics.median(v[j] for v in vals) for j in range(len(fields))]
    dist = lambda a,b: sum((x-y)**2 for x,y in zip(a,b))
    chosen = [min(range(len(rows)),key=lambda i:(dist(vals[i],centre),rows[i]['case']))]
    while len(chosen)<min(count,len(rows)):
        chosen.append(max((i for i in range(len(rows)) if i not in chosen),
                          key=lambda i:(min(dist(vals[i],vals[j]) for j in chosen),-i)))
    return {'selection':'log1p + min-max scaling + deterministic farthest-point coverage; no scores used',
            'fields':fields,'ordered_cases':[rows[i]['case'] for i in chosen],
            'development':[rows[i]['case'] for j,i in enumerate(chosen) if j%2==0],
            'confirmation':[rows[i]['case'] for j,i in enumerate(chosen) if j%2==1],
            'scope':'Confirmation is held out from this round of algorithm selection only. All official graphs were available in earlier work; no unseen-data generalisation claim.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',type=Path,required=True)
    a=ap.parse_args();p=a.project.resolve();out=p/'q1_cold';out.mkdir(exist_ok=True)
    sys.path.insert(0,str(p/'official/code'))
    from evaluation_validation import read_evaluation_config
    bandwidth=read_evaluation_config(str(p/'official/data/config.txt'))['bandwidth']
    rows=[]
    for f in sorted((p/'official/data').glob('case_*.json')):
        raw=f.read_bytes();g=json.loads(raw)
        rows.append(dict(case=f.stem,input_sha256=hashlib.sha256(raw).hexdigest(),**profile(g,bandwidth)))
    with (out/'input_profiles.csv').open('w',encoding='utf-8',newline='') as s:
        w=csv.DictWriter(s,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    samples=select_samples(rows)
    (out/'sampling.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={'cases':len(rows),'non_copy_pipes':'actual pipe field; never inferred from op name',
             'ranges':{k:[min(r[k] for r in rows),max(r[k] for r in rows)] for k in rows[0] if k not in ('case','input_sha256')},
             'no_rows_filtered':True,'input_modified':False}
    (out/'profile_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'samples':samples,'summary':summary},ensure_ascii=False))


if __name__=='__main__':main()
