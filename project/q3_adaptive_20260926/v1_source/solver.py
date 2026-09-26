"""Scene-B plus FIFO L2: bounded, deterministic input-adaptive cold inference."""
import argparse
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

from baseline import make_plan
from engine import InputGraph
from q1_optimized import (first_join_plan, terminal_branch_plan, fork_join_plan,
                          depth_band_plan, valley_stage_plan)

SOURCES = ('solver.py','engine.py','graph_model.py','baseline.py','q1_optimized.py','policy.json')


def hardware(path):
    cfg, section = {}, None
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.split('#',1)[0].strip()
        if not line: continue
        if line.startswith('['):
            section = line[1:-1]; cfg[section] = {}
        else:
            key,value = line.split()
            cfg[section][key] = int(value)
    return cfg


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def reorder_components(g, plan):
    """Only reorder independent atomic components; never introduce fake waits."""
    m,_,groups = g.view(plan)
    reads,work = {},{}
    for sg,ops in groups.items():
        reads[sg] = set().union(*(g.inputs_by_op[o] for o in ops))
        work[sg] = max(sum(g.ops[o]['cycles'] for o in ops if g.ops[o]['pipe']==p)
                       for p in ('PIPE_M','PIPE_V'))
    schedules, leader = [],set()
    for core,row in enumerate(plan['core_schedules']):
        todo,seq,last = set(row),[],set()
        while todo:
            def priority(s):
                amount = lambda ts:sum(g.tensors[t]['size'] for t in ts)
                if not seq:
                    if core==0:
                        return (amount(reads[s])/g.bw+work[s],s)
                    return (amount(reads[s]&leader)/g.bw, -work[s],s)
                return (-amount(reads[s]&last)/g.cache_bw, -work[s],s)
            chosen = min(todo,key=priority)
            seq.append(chosen); todo.remove(chosen); last=reads[chosen]
            if core==0 and len(seq)==1: leader=set(last)
        schedules.append(seq)
    result = dict(node_to_subgraph=plan['node_to_subgraph'],core_schedules=schedules)
    g.validate(result)
    return result


def candidates(graph,n,cfg):
    g = InputGraph(graph,n,cfg)
    if n==1:
        return g,[dict(name='single_core_fixed',plan=make_plan(graph,1))],[]
    w=g.width
    builders = [
        ('component_vector',lambda:g.component_plan()),
        ('component_affinity',lambda:g.component_plan(True)),
        ('join_tail',lambda:first_join_plan(graph,n)),
        ('shared_prefix',lambda:terminal_branch_plan(graph,n)),
        ('fork_join',lambda:fork_join_plan(graph,n,min_band_depth=w)),
        ('data_band',lambda:depth_band_plan(graph,n,w,data_aware=True)),
        ('valley',lambda:valley_stage_plan(graph,n,split_shared=True,narrow_rule='mode',min_band_depth=w)),
        ('component_reuse_order',lambda:reorder_components(g,g.component_plan())),
    ]
    found,rejected,seen=[],[],set()
    for name,build in builders:
        try:
            plan=build()
            g.validate(plan)
            sig=fingerprint(plan)
            if sig in seen: continue
            seen.add(sig)
            stats=g.describe(plan)
            found.append(dict(name=name,plan=plan,plan_sha256=sig,**stats))
        except (ValueError,KeyError,RuntimeError,ZeroDivisionError) as exc:
            rejected.append(dict(name=name,error=str(exc)))
    if not found:
        # A full graph on one physical core always preserves the original DAG.
        plan=make_plan(graph,1)
        plan['core_schedules'].extend([] for _ in range(n-1))
        g.validate(plan)
        found=[dict(name='single_active_core_fallback',plan=plan,
                    plan_sha256=fingerprint(plan),**g.describe(plan))]
    return g,found,rejected


def solve(graph,n,cfg,policy):
    if n not in range(1,6): raise ValueError('core count must be 1–5')
    g,rows,rejected=candidates(graph,n,cfg)
    if n==1:
        best=rows[0]
    else:
        for r in rows:
            r['score_cycles']=r['event_cycles']+policy['spill_weight']*r['spill_cycles']
        best=min(rows,key=lambda r:(r['score_cycles'],r['projected_copy_bytes'],r['name']))
    return best['plan'],dict(version=policy['version'],profile=g.profile,
                            selected=best['name'],plan_sha256=fingerprint(best['plan']),
                            policy=policy,rejected=rejected,
                            candidates=[{k:v for k,v in r.items() if k!='plan'} for r in rows],
                            official_evaluator_calls=0)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('graph',type=Path)
    ap.add_argument('-n','--cores',type=int,required=True)
    ap.add_argument('--config',type=Path,required=True)
    ap.add_argument('-o','--output',type=Path,required=True)
    ap.add_argument('--report',type=Path)
    args=ap.parse_args()
    start=time.perf_counter()
    policy=json.loads(Path(__file__).with_name('policy.json').read_text(encoding='utf-8'))
    graph=json.loads(args.graph.read_text(encoding='utf-8'))
    plan,report=solve(graph,args.cores,hardware(args.config),policy)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(plan,separators=(',',':'))+'\n',encoding='utf-8')
    report['inference_seconds']=time.perf_counter()-start
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(args.output)


if __name__=='__main__':
    main()
