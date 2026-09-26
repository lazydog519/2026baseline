"""Size follow-up after the small audit; keep the algorithm unchanged."""
import json
import random
import shutil
import subprocess
import sys
import time
from audit import ROOT, PROJECT, SEED, dump, graph, sha

rng=random.Random(SEED+1)
graphs={}
for layers in (24,48):
    parents=[[] for _ in range(24)]
    for i in range(24,layers*24):
        prev=range((i//24-1)*24,(i//24)*24)
        parents.append(sorted(rng.sample(list(prev),2)))
    graphs[f'layered_{layers*24}']=graph(parents,size=8192,mixed=True)
dump(ROOT/'medium_protocol.json',dict(reason='Check non-toy input sizes after the first audit',
    seed=SEED+1,graphs={k:len([o for o in v['ops'] if o['op'] not in ('COPY_IN','COPY_OUT')]) for k,v in graphs.items()},
    cores=5,official_calls_limit=8,solver_changed=False))
for q in (1,2):
    origin=ROOT/f'isolated_q{q}'; f=ROOT/f'medium_q{q}'; (f/'inputs').mkdir(parents=True,exist_ok=True)
    for p in origin.iterdir():
        if p.suffix=='.py' or p.name in ('config.txt','policy.json'): shutil.copy2(p,f/p.name)
    shutil.copy2(origin/'inputs/serial.json',f/'inputs/serial.json')
    for name,g in graphs.items(): dump(f/'inputs'/f'{name}.json',g)
    dump(f/'jobs.json',[dict(name=name,file=name+'.json',cores=5,kind='base') for name in graphs])
    cp=subprocess.run([sys.executable,'-I',str(f/'infer_worker.py'),str(q)],cwd=f,capture_output=True,text=True,timeout=90)
    if cp.returncode: raise RuntimeError(cp.stderr)
frozen={str(p.relative_to(ROOT)):sha(p) for p in ROOT.glob('medium_*/inference.json')}
dump(ROOT/'medium_frozen.json',frozen)
sys.path.insert(0,str(PROJECT/'official/code'))
from evaluation_validation import validate_graph,read_evaluation_config
from multicore_cut_evaluate_problem_1 import evaluate_scene_a,read_scene_a_config
from multicore_cut_evaluate_problem_2 import evaluate_scene_b,read_scene_b_config
cfg=str(PROJECT/'official/data/config.txt'); kw=read_evaluation_config(cfg)
ac=read_scene_a_config(cfg); bc=read_scene_b_config(cfg); rows=[]
for g in graphs.values(): validate_graph(g)
for q in (1,2):
    data=json.loads((ROOT/f'medium_q{q}/inference.json').read_text(encoding='utf-8'))
    assert not data['official_modules']
    for job in data['jobs']:
        for label,key in [('selected','plan'),('component','component')]:
            r=dict(question=q,name=job['name'],plan=label,inference_seconds=job['seconds'])
            t=time.perf_counter()
            try:
                assert job['status']=='generated',job
                if q==1: out=evaluate_scene_a(graphs[job['name']],job[key],**kw,same_core_wait=ac['task_same_core_wait_cycles'],cross_core_wait=ac['task_cross_core_wait_cycles'])
                else: out=evaluate_scene_b(graphs[job['name']],job[key],**kw,cross_core_copy_delay=bc['cross_core_copy_delay_cycles'])
                assert all(v[p]<=kw['capacity'][p] for v in out['memory_peak_by_core'].values() for p in ('L1','UB'))
                r.update(status='ok',makespan=out['makespan'],spill_bytes=out['data_movement_bytes']['spill_added_copy_bytes'])
            except Exception as exc: r.update(status='error',error=repr(exc))
            r['audit_seconds']=time.perf_counter()-t; rows.append(r)
            dump(ROOT/'medium_results.json',rows)
assert all(sha(ROOT/p)==h for p,h in frozen.items())
print(json.dumps(rows,indent=2))
