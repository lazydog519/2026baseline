"""Cold construction and legal, event-guided ordering for problem 3.

Only the current graph, configuration and source code are inputs. No stored
answers, case-name conditions, prefilled Cache, fabricated ops or sleeps.
"""
import argparse
import gzip
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

P=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(P/'solution'),str(P/'official/code')]
from baseline import make_plan
from q1_optimized import compute_dag,topological_depth,depth_band_plan
from evaluation_validation import read_evaluation_config,validate_task_order
from stub_multicore_cut_and_schedule import derive_multicore_plan
from multicore_cut_evaluate_problem_3 import evaluate_problem_3,read_cache_config,read_scene_b_config
from contest_io import _read_json


def fp(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class GraphView:
    def __init__(self,g):
        self.g=g;self.ops,self.pred,self.succ=compute_dag(g)
        self.order,self.depth=topological_depth(self.ops,self.pred,self.succ)
        prod,cons=defaultdict(set),defaultdict(set)
        for e in g['edges']:
            if e['source'] in self.ops:prod[e['target']].add(e['source'])
            if e['target'] in self.ops:cons[e['source']].add(e['target'])
        self.inputs={t['id']:(t['size'],cons[t['id']]) for t in g['tensors'] if cons[t['id']] and not prod[t['id']]}

    def component_blocks(self,base,limit):
        visited=set();pieces=defaultdict(list)
        for o in sorted(self.ops):
            if o in visited:continue
            stack=[o];visited.add(o);group=[]
            while stack:
                v=stack.pop();group.append(v)
                for x in sorted(self.pred[v]|self.succ[v]):
                    if x not in visited:visited.add(x);stack.append(x)
            work=defaultdict(int)
            for v in group:work[self.ops[v]['pipe']]+=self.ops[v]['cycles']
            core=next(k for k,s in enumerate(base['core_schedules']) if base['node_to_subgraph'][str(o)] in s)
            pieces[core].append((max(work.values()),min(group),group))
        n=len(base['core_schedules']);mapping={};schedules=[[] for _ in range(n)];sg=0
        for core in range(n):
            ordered=sorted(pieces[core],key=lambda x:(-x[0],x[1]))
            chunk=max(1,math.ceil(len(ordered)*n/limit))
            for start in range(0,len(ordered),chunk):
                for _,_,members in ordered[start:start+chunk]:mapping.update({str(o):sg for o in members})
                schedules[core].append(sg);sg+=1
        return dict(node_to_subgraph=mapping,core_schedules=schedules)

    def feedback(self,plan,result,cfg,bw):
        mapping={int(o):s for o,s in plan['node_to_subgraph'].items()}
        sg_inputs=defaultdict(set)
        for tid,(_,cons) in self.inputs.items():
            for o in cons:sg_inputs[mapping[o]].add(tid)
        accesses=defaultdict(list);insertions=defaultdict(list)
        lookup={(c['core_id'],o['op_id']):o for c in result['per_core_timeline'] for o in c['ops']}
        for e in result['cache_events']:
            if e['event'] in ('hit','miss'):accesses[e['tensor_id']].append(e)
            elif e['event']=='insert':insertions[e['tensor_id']].append(e['time'])
        targets=sorted((tid for tid in accesses if len(accesses[tid])>1 and insertions[tid]),
                       key=lambda tid:(-sum(e['size_bytes'] for e in accesses[tid] if e['event']=='miss'),tid))
        proposals=[]
        for tid in targets[:cfg['max_target_tensors']]:
            events=accesses[tid]
            if len(events)<2 or not insertions[tid]:continue
            first_fill=min(insertions[tid])
            misses=[e for e in events if e['event']=='miss']
            leader=min(misses,key=lambda e:(lookup[e['core_id'],e['op_id']]['end'],e['core_id']))
            for e in misses:
                core=e['core_id'];op=lookup[core,e['op_id']];target=op['subgraph_id']
                seq=plan['core_schedules'][core]
                if target not in seq:continue
                index=seq.index(target)
                if e['time']<first_fill and core!=leader['core_id']:
                    for j in range(index+1,len(seq)):
                        other=seq[j]
                        if tid in sg_inputs[other]:continue
                        byte_count=sum(self.inputs[x][0] for x in sg_inputs[other])
                        if not byte_count:continue
                        order=seq[:index]+[other]+seq[index:j]+seq[j+1:]
                        score=abs(byte_count/bw-(first_fill-e['time']))
                        proposals.append((score,core,target,other,'natural_stagger',order,tid))
                elif e['time']>=first_fill and index>0:
                    # A later miss may have missed a residence interval. Moving
                    # an existing consumer earlier is only a candidate, not proof.
                    order=[target]+seq[:index]+seq[index+1:]
                    proposals.append((e['time']-first_fill,core,target,target,'earlier_consumer',order,tid))
        for score,core,target,other,mode,order,tid in sorted(proposals,key=lambda x:x[:4]):
            schedules=[list(s) for s in plan['core_schedules']];schedules[core]=order
            candidate=dict(node_to_subgraph=dict(plan['node_to_subgraph']),core_schedules=schedules)
            try:validate_task_order(derive_multicore_plan(self.g,candidate))
            except (ValueError,RuntimeError):continue
            yield mode,candidate,dict(tensor_id=tid,core=core,target_sg=target,moved_sg=other,proxy_gap_cycles=score)


def solve(graph,n,fixed,cfg,out):
    out.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    hw=read_evaluation_config(str(fixed));cache=read_cache_config(str(fixed));scene=read_scene_b_config(str(fixed))
    kwargs=dict(bandwidth=hw['bandwidth'],capacity=hw['capacity'],cross_core_copy_delay=scene['cross_core_copy_delay_cycles'],**cache)
    model=GraphView(graph);seen=set();events=[];history=[];best=None;best_result=None;best_key=(math.inf,math.inf);calls=0
    target=out/'plan.json'
    def emit(row):
        events.append(row)
        with (out/'search.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    (out/'search.jsonl').write_text('',encoding='utf-8')
    def evaluate(name,plan,meta=None):
        nonlocal calls,best,best_result,best_key
        digest=fp(plan)
        if digest in seen or calls>=cfg['max_official_evaluations']:return
        seen.add(digest);begin=time.perf_counter()
        row=dict(candidate=name,plan_sha256=digest,details=meta or {},blocks=len(set(plan['node_to_subgraph'].values())))
        try:
            calls+=1
            result=evaluate_problem_3(graph,plan,**kwargs)
            history.append((name,plan,result))
            assert all(x[k]<=hw['capacity'][k] for x in result['memory_peak_by_core'].values() for k in ('L1','UB'))
            assert all(e['used_bytes']<=cache['cache_capacity_bytes'] for e in result['cache_events'] if e['event']=='insert')
            key=(result['makespan'],result['data_movement_bytes']['added_copy_bytes']);accepted=key<best_key
            if accepted:
                best,best_result,best_key=plan,result,key
                target.write_text(json.dumps(plan,separators=(',',':'))+'\n',encoding='utf-8')
            name_stem=f'eval_{calls:02d}'
            (out/(name_stem+'_plan.json')).write_text(json.dumps(plan,separators=(',',':'))+'\n',encoding='utf-8')
            with gzip.open(out/(name_stem+'.json.gz'),'wt',encoding='utf-8') as f:json.dump(result,f,separators=(',',':'))
            row.update(status='ok',evaluation=calls,makespan=result['makespan'],added_copy_bytes=key[1],
                hit_rate=result['cache_stats']['hit_rate'],hit_bytes=result['cache_stats']['hit_bytes'],
                accepted=accepted,best_makespan=best_key[0])
        except (ValueError,RuntimeError) as exc:
            row.update(status='invalid',evaluation=calls,error=str(exc),error_type=type(exc).__name__)
        row.update(seconds=time.perf_counter()-begin,elapsed_seconds=time.perf_counter()-started);emit(row)
    packed=make_plan(graph,n);evaluate('component_packing',packed)
    evaluate('component_blocks',model.component_blocks(packed,cfg['max_initial_blocks_target']))
    depth=max(model.depth.values());width=max(2,math.ceil(math.sqrt(depth)),math.ceil(depth*n/cfg['max_initial_blocks_target']))
    for _ in range(cfg['max_scale_trials']):
        band=depth_band_plan(graph,n,width,data_aware=True)
        if len(set(band['node_to_subgraph'].values()))<=cfg['max_initial_blocks_target']:break
        width*=2
    evaluate('data_aware_bands',band,dict(width=width))
    if best is None:raise RuntimeError('No feasible construction')
    proposals=[]
    for anchor,plan,result in history:
        for j,(name,candidate,meta) in enumerate(model.feedback(plan,result,cfg,hw['bandwidth'])):
            proposals.append((result['makespan'],anchor,name,candidate,dict(meta,anchor=anchor)))
            if j+1>=cfg['feedback_candidates']:break
    count=0
    for _,anchor,name,plan,meta in sorted(proposals,key=lambda x:(x[0],x[1],x[4]['proxy_gap_cycles'])):
        if fp(plan) in seen:continue
        evaluate(name,plan,meta);count+=1
        if count>=cfg['feedback_candidates']:break
    with gzip.open(out/'selected_result.json.gz','wt',encoding='utf-8') as f:json.dump(best_result,f,separators=(',',':'))
    run=dict(version=cfg['version'],cold_start=True,historical_plans_read=False,initial_cache_empty=True,
        input_sha256=fp(graph),config_sha256=hashlib.sha256(fixed.read_bytes()).hexdigest(),algorithm_config=cfg,
        cores=n,selected_plan_sha256=fp(best),makespan=best_key[0],official_evaluations=calls,
        elapsed_seconds=time.perf_counter()-started,feedback_proposals_evaluated=count,
        invalid_candidates=sum(e['status']=='invalid' for e in events))
    (out/'run.json').write_text(json.dumps(run,indent=2)+'\n',encoding='utf-8')
    return best,best_result,run


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('graph',type=Path)
    ap.add_argument('-n',type=int,choices=range(1,6),required=True);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--config',type=Path);ap.add_argument('--parameters',type=Path,default=Path(__file__).with_name('pilot_config.json'))
    a=ap.parse_args();_,_,run=solve(_read_json(a.graph),a.n,a.config or a.graph.with_name('config.txt'),
        json.loads(a.parameters.read_text(encoding='utf-8')),a.output_dir)
    print(json.dumps(run),flush=True)


if __name__=='__main__':main()
