"""Discrete NPU plans with original pymoo NSGA-III survival / U-NSGA-III mating.

Every invocation reconstructs its initial plans from the current input only.
The official evaluator and config are unchanged; no persistent solution cache.
"""
import argparse
import gzip
import hashlib
import heapq
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import pymoo
from pymoo.core.population import Population
from pymoo.core.problem import Problem
from pymoo.algorithms.moo.nsga3 import ReferenceDirectionSurvival
from pymoo.algorithms.moo.unsga3 import comp_by_rank_and_ref_line_dist
from pymoo.util.ref_dirs import get_reference_directions

ROOT=Path(__file__).resolve().parent
P=ROOT.parent
sys.path[:0]=[str(P/'solution'),str(P/'official/code'),str(P/'q3_design')]
from baseline import make_plan
from q1_optimized import compute_dag,topological_depth,depth_band_plan
from q3_pilot_solver import GraphView,fp
from multicore_cut_evaluate_problem_3 import evaluate_problem_3,read_cache_config,read_scene_b_config
from evaluation_validation import read_evaluation_config


def canonical(plan):
    groups=defaultdict(list)
    for v,s in plan['node_to_subgraph'].items():groups[int(s)].append(int(v))
    ids={s:i for i,s in enumerate(sorted(groups,key=lambda s:min(groups[s])))}
    return dict(node_to_subgraph={str(v):ids[int(s)] for v,s in sorted(plan['node_to_subgraph'].items(),key=lambda x:int(x[0]))},
                core_schedules=[[ids[s] for s in seq] for seq in plan['core_schedules']])


class Model:
    def __init__(self,g,n,config):
        self.g=g;self.n=n;self.cfg=config
        self.ops,self.pred,self.succ=compute_dag(g)
        self.topo,self.depth=topological_depth(self.ops,self.pred,self.succ)
        self.position={v:i for i,v in enumerate(self.topo)}
        prod,cons=defaultdict(set),defaultdict(set)
        for e in g['edges']:
            if e['source'] in self.ops:prod[e['target']].add(e['source'])
            if e['target'] in self.ops:cons[e['source']].add(e['target'])
        self.tensors=[(t['size'],prod[t['id']],cons[t['id']]) for t in g['tensors'] if prod[t['id']] or cons[t['id']]]
        self.direct=[(e['source'],e['target'],int(e.get('data_size',0))) for e in g['edges'] if e['source'] in self.ops and e['target'] in self.ops]

    def parts(self,plan):
        mapping={int(v):int(s) for v,s in plan['node_to_subgraph'].items()}
        groups=defaultdict(list)
        for v in self.topo:groups[mapping[v]].append(v)
        cores={s:k for k,seq in enumerate(plan['core_schedules']) for s in seq}
        return groups,cores

    def repair(self,groups,cores,priority):
        mapping={v:s for s,vs in groups.items() for v in vs}
        assert set(mapping)==set(self.ops) and sum(map(len,groups.values()))==len(self.ops)
        succ={s:set() for s in groups};indeg={s:0 for s in groups}
        for v in self.topo:
            for u in self.succ[v]:
                a,b=mapping[v],mapping[u]
                if a!=b:succ[a].add(b)
        for a in succ:
            for b in succ[a]:indeg[b]+=1
        heap=[(priority[s],min(groups[s]),s) for s in groups if indeg[s]==0];heapq.heapify(heap)
        order=[]
        while heap:
            _,_,s=heapq.heappop(heap);order.append(s)
            for v in sorted(succ[s]):
                indeg[v]-=1
                if indeg[v]==0:heapq.heappush(heap,(priority[v],min(groups[v]),v))
        if len(order)!=len(groups):raise ValueError('partition contraction has a directed cycle')
        schedules=[[] for _ in range(self.n)]
        for s in order:schedules[cores[s]].append(s)
        return canonical(dict(node_to_subgraph={str(v):s for v,s in mapping.items()},core_schedules=schedules)),order

    def work(self,groups):
        return {s:np.array([sum(self.ops[v]['cycles'] for v in vs if self.ops[v]['pipe']=='PIPE_M'),
                           sum(self.ops[v]['cycles'] for v in vs if self.ops[v]['pipe']!='PIPE_M')],dtype=float) for s,vs in groups.items()}

    def communication_proxy(self,groups,cores):
        loc={v:cores[s] for s,vs in groups.items() for v in vs};total=0
        for size,prod,cons in self.tensors:
            a={loc[v] for v in prod};b={loc[v] for v in cons}
            if not a:total+=len(b)*size
            else:total+=2*size*sum(x!=y for x in a for y in b)
        total+=sum(2*b for u,v,b in self.direct if loc[u]!=loc[v])
        return total

    def core_choice(self,groups,cores,target,bw):
        work=self.work(groups);scores=[]
        for k in range(self.n):
            trial=dict(cores);trial[target]=k;load=np.zeros((self.n,2))
            for s,w in work.items():load[trial[s]]+=w
            scores.append((float(load.max())+self.communication_proxy(groups,trial)/bw,k))
        return min(scores)[1]

    def propose(self,parent,donor,rng,engineering,bw,cross=False):
        groups,cores=self.parts(parent['plan'])
        # This global order is a conservative structural repair, not an added
        # whole-subgraph execution barrier in the official simulator.
        priority={s:float(i) for seq in parent['plan']['core_schedules'] for i,s in enumerate(seq)}
        _,order=self.repair(groups,cores,priority)
        priority={s:float(i) for i,s in enumerate(order)}
        info={}
        if cross:
            dgroups,dcores=self.parts(donor['plan'])
            donor_core={v:dcores[s] for s,vs in dgroups.items() for v in vs}
            for s in sorted(groups):
                if rng.random()<.5:
                    counts=Counter(donor_core[v] for v in groups[s])
                    cores[s]=min(counts,key=lambda c:(-counts[c],c))
            info['crossover']='whole_subgraph_donor_majority'
        mode=str(rng.choice(self.cfg['mutation_types']));work=self.work(groups)
        result=parent['result']
        finish={c['core_id']:max((o['end'] for o in c['ops']),default=0) for c in result['per_core_timeline']}
        critical=min(range(self.n),key=lambda k:(-finish[k],k))
        if mode=='move':
            choices=[s for s in groups if cores[s]==critical] if engineering else list(groups)
            if not choices:choices=list(groups)
            s=int(rng.choice(sorted(choices)));old=cores[s]
            new=self.core_choice(groups,cores,s,bw) if engineering else int(rng.integers(self.n))
            if new==old and self.n>1:new=int(rng.choice([k for k in range(self.n) if k!=old]))
            cores[s]=new;info.update(subgraph=s,from_core=old,to_core=new)
        elif mode=='split':
            choices=[s for s in groups if len(groups[s])>1]
            if choices and len(groups)<self.cfg['max_subgraphs']:
                s=(min(choices,key=lambda s:(-max(work[s])*(1+int(cores[s]==critical)),s)) if engineering else int(rng.choice(sorted(choices))))
                vs=groups[s];m=len(vs)
                positions=sorted(set(int(x) for x in np.linspace(max(1,m//3),min(m-1,2*m//3),self.cfg['split_cut_candidates'])))
                def cutbytes(k):
                    left=set(vs[:k]);right=set(vs[k:])
                    return sum(size for size,prod,cons in self.tensors if prod&left and cons&right)+sum(b for u,v,b in self.direct if u in left and v in right)
                k=min(positions,key=lambda k:(cutbytes(k),abs(k-m/2),k)) if engineering else max(1,m//2)
                new=max(groups)+1;groups[s]=vs[:k];groups[new]=vs[k:];cores[new]=cores[s]
                priority[new]=priority[s]+.1
                cores[new]=self.core_choice(groups,cores,new,bw) if engineering else int(rng.integers(self.n))
                info.update(subgraph=s,new_subgraph=new,cut=k)
        elif mode=='merge':
            pairs=[(a,b) for a,b in zip(order,order[1:]) if cores[a]==cores[b]]
            if pairs:
                if engineering:
                    mapping={v:s for s,vs in groups.items() for v in vs}
                    def affinity(pair):
                        a,b=pair;value=0
                        for size,prod,cons in self.tensors:
                            touched={mapping[v] for v in prod|cons}
                            if a in touched and b in touched:value+=size
                        return value
                    a,b=min(pairs,key=lambda pair:(-affinity(pair),pair))
                else:a,b=pairs[int(rng.integers(len(pairs)))]
                groups[a]=sorted(groups[a]+groups.pop(b),key=self.position.get);cores.pop(b);priority.pop(b)
                info.update(merged=[a,b])
        else:
            if engineering:
                lookup={(c['core_id'],o['op_id']):o for c in result['per_core_timeline'] for o in c['ops']}
                miss=defaultdict(int)
                for e in result['cache_events']:
                    if e['event']=='miss':
                        s=lookup[e['core_id'],e['op_id']]['subgraph_id']
                        if s in groups:miss[s]+=e['size_bytes']
                s=min(miss,key=lambda s:(-miss[s],s)) if miss else int(rng.choice(sorted(groups)))
                priority[s]=-1.;info['prioritized_subgraph']=s
            else:
                a,b=rng.choice(sorted(groups),2,replace=False) if len(groups)>1 else (next(iter(groups)),)*2
                priority[a],priority[b]=priority[b],priority[a]
        plan,_=self.repair(groups,cores,priority)
        return plan,dict(operator=mode,engineering=engineering,**info)

    def initial(self):
        packed=make_plan(self.g,self.n)
        yield 'component_packing',packed
        yield 'component_blocks',GraphView(self.g).component_blocks(packed,128)
        depth=max(self.depth.values());width=max(2,math.ceil(math.sqrt(depth)),math.ceil(depth*self.n/128))
        for _ in range(4):
            band=depth_band_plan(self.g,self.n,width,data_aware=True)
            if len(set(band['node_to_subgraph'].values()))<=128:break
            width*=2
        yield 'data_aware_bands',band


def run(graph,n,hardware,cfg,method,seed,out):
    out.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(seed);model=Model(graph,n,cfg)
    hw=read_evaluation_config(str(hardware));sc=read_scene_b_config(str(hardware))
    kwargs=dict(bandwidth=hw['bandwidth'],capacity=hw['capacity'],cross_core_copy_delay=sc['cross_core_copy_delay_cycles'],**read_cache_config(str(hardware)))
    records=[];seen=set();calls=0;attempts=0;invalid=[];checkpoints=[];started=time.perf_counter()
    def evaluate(plan,phase,details=None):
        nonlocal calls
        plan=canonical(plan);digest=fp(plan)
        if digest in seen or calls>=cfg['official_budget']:return None
        seen.add(digest);calls+=1
        row=dict(evaluation=calls,phase=phase,plan_sha256=digest,details=details or {})
        try:
            result=evaluate_problem_3(graph,plan,**kwargs)
            assert all(x[k]<=hw['capacity'][k] for x in result['memory_peak_by_core'].values() for k in ('L1','UB'))
            rec=dict(plan=plan,result=result,F=[result['makespan'],result['data_movement_bytes']['added_copy_bytes'],result['cache_stats']['miss_bytes']],hash=digest)
            records.append(rec);row.update(status='ok',objectives=rec['F'],hit_rate=result['cache_stats']['hit_rate'])
        except (ValueError,RuntimeError) as exc:
            invalid.append(dict(error=str(exc),error_type=type(exc).__name__,plan=plan,**row))
            row.update(status='invalid',error=str(exc),error_type=type(exc).__name__);rec=None
            # Infeasibility has no fabricated numeric magnitude; record the
            # evaluator's exact violated constraint and exclude from survival.
        row.update(elapsed_seconds=time.perf_counter()-started,
                   best_makespan=min((r['F'][0] for r in records),default=None))
        with (out/'evaluations.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
        return rec
    (out/'evaluations.jsonl').write_text('',encoding='utf-8')
    for label,plan in model.initial():evaluate(plan,'construction',dict(name=label))
    if not records:raise RuntimeError('No feasible initial construction')
    construction_best=min(r['F'][0] for r in records)
    # All variants use exactly the same generic initialization for each seed.
    while len(records)<cfg['population'] and calls<cfg['official_budget'] and attempts<cfg['max_proposals_per_budget']*cfg['official_budget']:
        attempts+=1;parent=records[int(rng.integers(len(records)))]
        plan,meta=model.propose(parent,parent,rng,False,hw['bandwidth'])
        evaluate(plan,'initial_population',meta)
    initial_hashes=[r['hash'] for r in records]
    ref=get_reference_directions('das-dennis',3,n_partitions=cfg['reference_partitions'])
    survival=ReferenceDirectionSurvival(ref)
    problem=Problem(n_var=1,n_obj=3)
    def select(ids):
        pop=Population.new(F=np.array([records[i]['F'] for i in ids],float),idx=np.array(ids,int))
        return survival.do(problem,pop,n_survive=min(cfg['population'],len(pop)),random_state=rng)
    pop=select(list(range(len(records))));generation=0
    def checkpoint():
        row=dict(generation=generation,official_calls=calls,
                 best_makespan=min(r['F'][0] for r in records),
                 population_ids=[int(i) for i in pop.get('idx')],elapsed_seconds=time.perf_counter()-started)
        checkpoints.append(row)
        with (out/'generations.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
    (out/'generations.jsonl').write_text('',encoding='utf-8');checkpoint()
    while calls<cfg['official_budget'] and attempts<cfg['max_proposals_per_budget']*cfg['official_budget']:
        generation+=1;new_ids=[];before=calls
        def parent_id():
            if method=='unsga3_npu' and len(pop)>1:
                pair=rng.choice(len(pop),2,replace=False).reshape(1,2)
                i=int(comp_by_rank_and_ref_line_dist(pop,pair,random_state=rng)[0,0])
            else:i=int(rng.integers(len(pop)))
            return int(pop[i].get('idx'))
        while calls-before<cfg['offspring_batch'] and calls<cfg['official_budget'] and attempts<cfg['max_proposals_per_budget']*cfg['official_budget']:
            attempts+=1;a=parent_id();b=parent_id()
            try:
                plan,meta=model.propose(records[a],records[b],rng,method!='nsga3_generic',hw['bandwidth'],rng.random()<cfg['crossover_probability'])
            except ValueError as exc:
                invalid.append(dict(stage='structural_repair',error=str(exc)));continue
            rec=evaluate(plan,'offspring',dict(generation=generation,parent=a,donor=b,**meta))
            if rec is not None:new_ids.append(len(records)-1)
        if new_ids:pop=select([int(i) for i in pop.get('idx')]+new_ids)
        checkpoint()
        if calls==before:break
    chosen=min(records,key=lambda r:(r['F'][0],r['F'][1]));result=chosen['result']
    assert all(b['best_makespan']<=a['best_makespan'] for a,b in zip(checkpoints,checkpoints[1:]))
    (out/'plan.json').write_text(json.dumps(chosen['plan'],separators=(',',':'))+'\n',encoding='utf-8')
    with gzip.open(out/'result.json.gz','wt',encoding='utf-8') as f:json.dump(result,f,separators=(',',':'))
    with gzip.open(out/'candidates.jsonl.gz','wt',encoding='utf-8') as f:
        for r in records:f.write(json.dumps(dict(plan=r['plan'],objectives=r['F'],sha256=r['hash']),separators=(',',':'))+'\n')
    summary=dict(version=cfg['version'],method=method,seed=seed,cores=n,pymoo_version=pymoo.__version__,
        input_sha256=fp(graph),hardware_sha256=hashlib.sha256(hardware.read_bytes()).hexdigest(),
        official_calls=calls,feasible_evaluations=len(records),invalid_records=len(invalid),
        proposals=attempts,generations=generation,initial_population_hashes=initial_hashes,
        construction_best=construction_best,makespan=result['makespan'],
        improvement_ratio=construction_best/result['makespan'],
        added_copy_bytes=result['data_movement_bytes']['added_copy_bytes'],
        cache_miss_bytes=result['cache_stats']['miss_bytes'],hit_rate=result['cache_stats']['hit_rate'],
        cold_start=True,historical_plans_read=False,empty_l2_each_evaluation=True,
        elapsed_seconds=time.perf_counter()-started,configuration=cfg)
    (out/'run.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    (out/'invalid.json').write_text(json.dumps(invalid,indent=2)+'\n',encoding='utf-8')
    return summary


def main():
    ap=argparse.ArgumentParser();ap.add_argument('graph',type=Path);ap.add_argument('-n',type=int,choices=range(1,6),required=True)
    ap.add_argument('--method',choices=['nsga3_generic','nsga3_npu','unsga3_npu'],required=True)
    ap.add_argument('--seed',type=int,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--config',type=Path);ap.add_argument('--parameters',type=Path,default=ROOT/'experiment.json')
    a=ap.parse_args();graph=json.loads(a.graph.read_text(encoding='utf-8'));cfg=json.loads(a.parameters.read_text(encoding='utf-8'))
    summary=run(graph,a.n,a.config or a.graph.with_name('config.txt'),cfg,a.method,a.seed,a.output)
    print(json.dumps({k:v for k,v in summary.items() if k not in ['configuration','initial_population_hashes']}),flush=True)


if __name__=='__main__':main()
