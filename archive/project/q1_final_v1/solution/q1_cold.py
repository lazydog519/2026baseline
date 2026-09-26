"""Independent scene-A construction, greedy scheduling and bounded improvement.

No answer database or learned case identifiers. The original evaluator is the
only acceptance function. The input graph and official code remain unchanged.
"""
import argparse
import gzip
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from heapq import heappop, heappush
from pathlib import Path

from baseline import make_plan
from q1_optimized import (compute_dag, topological_depth, depth_band_plan,
                          valley_stage_plan, fork_join_plan, terminal_branch_plan)


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Model:
    def __init__(self, graph, bandwidth, same_wait, cross_wait):
        self.g,self.bw,self.same,self.cross=graph,bandwidth,same_wait,cross_wait
        self.ops,self.pred,self.succ=compute_dag(graph)
        self.order,self.depth=topological_depth(self.ops,self.pred,self.succ)
        self.prod,self.cons=defaultdict(set),defaultdict(set)
        self.allops={o['id']:o for o in graph['ops']}
        for e in graph['edges']:
            if e['source'] in self.allops:self.prod[e['target']].add(e['source'])
            if e['target'] in self.allops:self.cons[e['source']].add(e['target'])
        self.cp={}
        for o in self.order:
            self.cp[o]=self.ops[o]['cycles']+max((self.cp[x] for x in self.pred[o]),default=0)

    def describe(self, plan):
        mapping={int(o):s for o,s in plan['node_to_subgraph'].items()}
        tasks=sorted(set(mapping.values()));n=len(plan['core_schedules'])
        core={s:k for k,seq in enumerate(plan['core_schedules']) for s in seq}
        pred={s:set() for s in tasks};succ={s:set() for s in tasks}
        work={s:defaultdict(int) for s in tasks}
        for o,s in mapping.items():
            work[s][self.ops[o]['pipe']]+=self.ops[o]['cycles']
            for x in self.succ[o]:
                t=mapping[x]
                if s!=t:succ[s].add(t);pred[t].add(s)
        degree={s:len(pred[s]) for s in tasks}
        heap=[]
        for s in tasks:
            if degree[s]==0:heappush(heap,s)
        order=[]
        while heap:
            s=heappop(heap);order.append(s)
            for t in sorted(succ[s]):
                degree[t]-=1
                if degree[t]==0:heappush(heap,t)
        if len(order)!=len(tasks):raise ValueError('contracted Task graph has a cycle')
        io={s:[0,0] for s in tasks};inputs={s:set() for s in tasks};outputs={s:set() for s in tasks}
        for tensor in self.g['tensors']:
            tid,b=tensor['id'],tensor['size']
            producers={mapping[o] for o in self.prod[tid] if o in mapping}
            consumers={mapping[o] for o in self.cons[tid] if o in mapping}
            final=any(self.allops[o]['op']=='COPY_OUT' for o in self.cons[tid])
            for s in consumers-producers:io[s][0]+=b;inputs[s].add(tid)
            for s in producers:
                if final or not consumers or consumers-{s}:io[s][1]+=b;outputs[s].add(tid)
        duration={s:max(max(work[s].values(),default=0),sum(io[s])/self.bw) for s in tasks}
        byte_count=sum(sum(x) for x in io.values())
        bypipe=[defaultdict(int) for _ in range(n)]
        for s in tasks:
            for pipe,w in work[s].items():bypipe[core[s]][pipe]+=w
        bound=max(max(self.cp.values(),default=0),byte_count/self.bw,
                  max((w for row in bypipe for w in row.values()),default=0))
        return dict(tasks=tasks,core=core,pred=pred,succ=succ,order=order,
                    work=work,io=io,inputs=inputs,outputs=outputs,duration=duration,bytes=byte_count,bound=bound)

    def estimate(self, plan, view=None):
        v=view or self.describe(plan)
        pred={s:set(v['pred'][s]) for s in v['tasks']}
        seqprev={}
        for seq in plan['core_schedules']:
            for a,b in zip(seq,seq[1:]):pred[b].add(a);seqprev[b]=a
        succ={s:set() for s in v['tasks']}
        for s,ps in pred.items():
            for t in ps:succ[t].add(s)
        deg={s:len(ps) for s,ps in pred.items()};heap=[];finish={}
        for s,d in deg.items():
            if d==0:heappush(heap,s)
        while heap:
            s=heappop(heap)
            release=max((finish[t]+(self.cross if v['core'][t]!=v['core'][s] else
                         self.same if seqprev.get(s)==t else 0) for t in pred[s]),default=0)
            finish[s]=release+v['duration'][s]
            for t in sorted(succ[s]):
                deg[t]-=1
                if deg[t]==0:heappush(heap,t)
        if len(finish)!=len(v['tasks']):raise ValueError('combined dependency/core-order cycle')
        return max(max(finish.values(),default=0),v['bytes']/self.bw)

    def greedy(self, plan):
        v=self.describe(plan);n=len(plan['core_schedules']);rank={}
        for s in reversed(v['order']):
            rank[s]=v['duration'][s]+max((self.same+rank[t] for t in v['succ'][s]),default=0)
        degree={s:len(v['pred'][s]) for s in v['tasks']};heap=[]
        for s,d in degree.items():
            if not d:heappush(heap,(-rank[s],s))
        free=[0.]*n;sequences=[[] for _ in range(n)];placed={};finish={}
        while heap:
            _,s=heappop(heap)
            def eft(k):
                release=max([free[k]+self.same if sequences[k] else 0]+[
                    finish[t]+(self.cross if placed[t]!=k else 0) for t in v['pred'][s]])
                return release+v['duration'][s]
            k=min(range(n),key=lambda c:(eft(c),len(sequences[c]),c))
            free[k]=finish[s]=eft(k);placed[s]=k;sequences[k].append(s)
            for t in sorted(v['succ'][s]):
                degree[t]-=1
                if degree[t]==0:heappush(heap,(-rank[t],t))
        return {'node_to_subgraph':dict(plan['node_to_subgraph']),'core_schedules':sequences}

    def coarsen(self, plan, limit, trials):
        # Only neighbouring tasks in a global topological order are merged.
        # Contraction is revalidated; proxy improvements still require real evaluation.
        current=plan
        for _ in range(limit):
            v=self.describe(current);base=self.estimate(current,v);choices=[]
            adjacent={(a,b) for seq in current['core_schedules'] for a,b in zip(seq,seq[1:])}
            sizes={t['id']:t['size'] for t in self.g['tensors']}
            pairs=[(a,b) for a,b in zip(v['order'],v['order'][1:]) if (a,b) in adjacent]
            affinity=lambda a,b:sum(sizes[t] for t in (v['inputs'][a]|v['outputs'][a]) & v['inputs'][b])
            for a,b in sorted(pairs,key=lambda x:(-affinity(*x),x))[:trials]:
                candidate={'node_to_subgraph':{o:(a if s==b else s) for o,s in current['node_to_subgraph'].items()},
                           'core_schedules':[[s for s in seq if s!=b] for seq in current['core_schedules']]}
                score=self.estimate(candidate)
                if score<base-1e-9:choices.append((score,a,b,candidate))
            if not choices:break
            current=min(choices,key=lambda x:x[:3])[3]
        return current


def solve(graph, cores, official_code, fixed_config, search, target, trace):
    sys.path.insert(0,str(official_code))
    from evaluation_validation import read_evaluation_config,validate_task_order
    from multicore_cut_evaluate_problem_1 import evaluate_scene_a,read_scene_a_config
    from stub_multicore_cut_and_schedule import derive_multicore_plan
    cfg=read_evaluation_config(str(fixed_config));sc=read_scene_a_config(str(fixed_config))
    kwargs=dict(bandwidth=cfg['bandwidth'],capacity=cfg['capacity'],
                same_core_wait=sc['task_same_core_wait_cycles'],cross_core_wait=sc['task_cross_core_wait_cycles'])
    model=Model(graph,cfg['bandwidth'],kwargs['same_core_wait'],kwargs['cross_core_wait'])
    total_by_pipe=defaultdict(int)
    for o in model.ops.values():total_by_pipe[o['pipe']]+=o['cycles']
    global_bound=max(max(model.cp.values(),default=0),max(total_by_pipe.values(),default=0)/cores)
    target.parent.mkdir(parents=True,exist_ok=True);trace.mkdir(parents=True,exist_ok=True)
    log=trace/'search.jsonl';log.write_text('',encoding='utf-8')
    started=time.perf_counter();events=[];seen=set();calls=0;best=None;bestresult=None;bestkey=(float('inf'),float('inf'));initial=None;selected=None
    def emit(row):
        events.append(row)
        with log.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    def evaluate(name,plan):
        nonlocal calls,best,bestresult,bestkey,initial,selected
        fp=fingerprint(plan)
        if fp in seen:return
        if best and plan['node_to_subgraph']==best['node_to_subgraph'] and sorted(plan['core_schedules'])==sorted(best['core_schedules']):
            emit(dict(name=name,status='core_renaming_skipped'));seen.add(fp);return
        seen.add(fp)
        t0=time.perf_counter();row=dict(name=name,fingerprint=fp)
        try:
            validate_task_order(derive_multicore_plan(graph,plan))
            view=model.describe(plan);row.update(task_count=len(view['tasks']),pre_spill_bytes=view['bytes'],lower_bound_cycles=view['bound'],estimate_cycles=model.estimate(plan,view))
            if view['bound']>bestkey[0]+1e-9:
                emit(dict(row,status='bound_pruned',best_cycles=bestkey[0]));return
            if calls>=search['max_evaluations']:return
            calls+=1;row['evaluation']=calls
            result=evaluate_scene_a(graph,plan,**kwargs);m=result['data_movement_bytes']
            assert view['bytes']==m['scheduled_copy_bytes']-m['spill_added_copy_bytes'],'boundary byte accounting differs from official'
            assert view['bound']<=result['makespan']+1e-6,'lower bound exceeds official result'
            assert all(x[p]<=cfg['capacity'][p] for x in result['memory_peak_by_core'].values() for p in ('L1','UB'))
            key=(result['makespan'],m['added_copy_bytes'])
            accepted=key<bestkey
            if accepted:
                best,bestresult,bestkey,selected=plan,result,key,name
                target.write_text(json.dumps(plan,separators=(',',':'))+'\n',encoding='utf-8')
            if initial is None:
                initial=result['makespan']
                with gzip.open(trace/'initial_result.json.gz','wt',encoding='utf-8',compresslevel=1) as f:json.dump(result,f,separators=(',',':'))
            row.update(status='ok',makespan_cycles=result['makespan'],added_copy_bytes=m['added_copy_bytes'],spill_bytes=m['spill_added_copy_bytes'],accepted=accepted,best_cycles=bestkey[0])
        except AssertionError:
            raise
        except (ValueError,RuntimeError) as exc:
            row.update(status='infeasible',error_type=type(exc).__name__,error=str(exc),best_cycles=bestkey[0] if best else None)
        row.update(evaluation_seconds=time.perf_counter()-t0,elapsed_seconds=time.perf_counter()-started)
        emit(row)
    baseline=make_plan(graph,cores)
    depth=max(model.depth.values());total=sum(o['cycles'] for o in model.ops.values())
    width=max(2,math.ceil(cores*model.cross*depth/max(1,total)),math.ceil(depth*cores/search['max_generated_tasks']))
    candidates=[];baseline_fp=fingerprint(baseline)
    if search['reuse_packing']:
        pack=[]
        for active in range(1,cores):
            plan=make_plan(graph,active);plan['core_schedules'].extend([] for _ in range(cores-active))
            pack.append((model.estimate(plan),f'reuse_pack_k{active}',0,plan))
        if pack:candidates.append(min(pack,key=lambda x:(x[0],x[1])))
    for name,build in [('valley',lambda w:valley_stage_plan(graph,cores,split_shared=True,narrow_rule='mode',min_band_depth=w)),
                       ('data_band',lambda w:depth_band_plan(graph,cores,w,data_aware=True)),
                       ('fork_join',lambda w:fork_join_plan(graph,cores,min_band_depth=w)),
                       ('terminal',lambda w:terminal_branch_plan(graph,cores))]:
        w=width
        for _ in range(6):
            plan=build(w)
            if len(set(plan['node_to_subgraph'].values()))<=search['max_generated_tasks']:break
            w*=2
        if fingerprint(plan)==baseline_fp:continue
        try:
            validate_task_order(derive_multicore_plan(graph,plan))
            v=model.describe(plan);score=model.estimate(plan,v)
            candidates.append((score,name,w,plan))
        except (ValueError,RuntimeError) as exc:emit(dict(name=name,status='construction_rejected',error=str(exc)))
    candidates=sorted(candidates,key=lambda x:(x[0],x[1]))
    for rank,(score,name,w,plan) in enumerate(candidates):
        emit(dict(name=name,width=w,status='proxy_shortlisted' if rank<search['structure_evaluations'] else 'proxy_budget_skipped',estimate_cycles=score))
    candidates=candidates[:search['structure_evaluations']]
    candidates.append((model.estimate(baseline),'component_baseline',0,baseline))
    certified=lambda: bool(best) and global_bound>0 and bestkey[0]<=global_bound*(1+search['cert_relative_gap'])+1e-9
    for _,name,w,plan in sorted(candidates,key=lambda x:(x[0],x[1])):
        if certified():break
        evaluate(name if w==0 else f'{name}_w{w}',plan)
    if best is None:raise RuntimeError('No legal initial candidate')
    if search['greedy_reschedule'] and not certified():evaluate('greedy_schedule',model.greedy(best))
    if search['greedy_merge'] and not certified():evaluate('greedy_coarsen',model.coarsen(best,search['merge_limit'],search['merge_pair_trials']))
    with gzip.open(trace/'official_result.json.gz','wt',encoding='utf-8',compresslevel=1) as f:json.dump(bestresult,f,separators=(',',':'))
    report=dict(schema=search['version'],cold_start=True,cores=cores,search_config=search,initial_width=width,
                graph_sha256=hashlib.sha256(json.dumps(graph,sort_keys=True).encode()).hexdigest(),config_sha256=hashlib.sha256(fixed_config.read_bytes()).hexdigest(),
                initial_cycles=initial,makespan_cycles=bestkey[0],added_copy_bytes=bestkey[1],evaluations=calls,
                selected=selected,selected_fingerprint=fingerprint(best),wall_seconds=time.perf_counter()-started,
                invalid_candidates=sum(e['status']=='infeasible' for e in events),bound_pruned=sum(e['status']=='bound_pruned' for e in events),
                global_lower_bound_cycles=global_bound,certificate_gap=bestkey[0]/global_bound-1 if global_bound>0 else None,
                stop_reason='certified_gap' if certified() else 'fixed_candidate_budget',history_read=False)
    (trace/'run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('graph',type=Path);ap.add_argument('-n','--num-cores',type=int,choices=range(2,6),required=True)
    ap.add_argument('-o','--output',type=Path);ap.add_argument('--trace-dir',type=Path)
    ap.add_argument('--official-code',type=Path,default=Path(__file__).resolve().parents[1]/'official/code')
    ap.add_argument('--config',type=Path);ap.add_argument('--search-config',type=Path,default=Path(__file__).with_name('q1_cold_config.json'))
    a=ap.parse_args();target=a.output or a.graph.with_name(a.graph.stem+'_multicore_res.json');trace=a.trace_dir or target.with_name(target.stem+'_search')
    sys.path.insert(0,str(a.official_code))
    from contest_io import _read_json
    r=solve(_read_json(a.graph),a.num_cores,a.official_code,a.config or a.graph.with_name('config.txt'),
            json.loads(a.search_config.read_text(encoding='utf-8')),target,trace)
    print(json.dumps(r,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
