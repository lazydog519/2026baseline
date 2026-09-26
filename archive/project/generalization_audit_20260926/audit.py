"""Small, predeclared, out-of-development structural audit. No solver tuning."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
SEED = 26092617


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph(parents, size=1024, mixed=False, shared=False, direct=False, mte=False):
    rng = random.Random(SEED + len(parents))
    tensors, ops, edges = [], [], []
    next_id = 1
    def tensor(pos):
        nonlocal next_id
        i = next_id; next_id += 1
        tensors.append(dict(id=i, pos=pos, size=size)); return i
    def op(name, pipe, cycles):
        nonlocal next_id
        i = next_id; next_id += 1
        ops.append(dict(id=i, op=name, pipe=pipe, cycles=cycles)); return i
    def edge(a,b):
        edges.append(dict(source=a, target=b))
    outputs, compute = {}, {}
    shared_tensor = None
    for j, ps in enumerate(parents):
        inputs = [outputs[p] for p in ps]
        if not inputs:
            if shared and shared_tensor is not None:
                inputs = [shared_tensor]
            else:
                a, b = tensor('DDR'), tensor('UB')
                o = op('COPY_IN','PIPE_MTE2',1)
                edge(a,o); edge(o,b); inputs=[b]
                if shared: shared_tensor=b
        pipe = 'PIPE_M' if mixed and j%2 else 'PIPE_V'
        if mte and j%3 == 1: pipe='PIPE_MTE2'
        o = op('LOCAL_MOVE' if pipe=='PIPE_MTE2' else 'COMPUTE', pipe,
               rng.choice([80, 300, 1500, 7000, 20000]))
        t = tensor('L1' if pipe=='PIPE_M' else 'UB')
        for a in inputs: edge(a,o)
        edge(o,t); outputs[j]=t; compute[j]=o
    consumed = {p for ps in parents for p in ps}
    for j in set(range(len(parents)))-consumed:
        o, t = op('COPY_OUT','PIPE_MTE3',1), tensor('DDR')
        edge(outputs[j],o); edge(o,t)
    if direct:
        # A legal direct dependency between independent chains, absent in the 100 original graphs.
        edges.append(dict(source=compute[3], target=compute[7], data_size=8192))
    return dict(ops=ops, tensors=tensors, edges=edges)


def prepare():
    rng=random.Random(SEED)
    chains=[[] if i%4==0 else [i-1] for i in range(32)]
    irregular=[[] for _ in range(5)]
    for i in range(5,40):
        prev=list(range(max(0,(i//5-1)*5),(i//5)*5))
        irregular.append(sorted(rng.sample(prev,rng.choice([1,2,3]))))
    specs={
      'serial':graph([[]]+[[i-1] for i in range(1,24)],mixed=True),
      'independent':graph(chains,mixed=True),
      'fork_join':graph([[]]+[[0] for _ in range(8)]+[list(range(1,9))]+[[i-1] for i in range(10,16)]),
      'irregular':graph(irregular,mixed=True),
      'pressure':graph([[]]+[sorted({i-1,max(0,i-5)}) for i in range(1,20)],size=40000),
      'shared_input':graph(chains,size=24000,shared=True),
      'direct_dependency':graph(chains,direct=True),
      'transfer_pipe':graph(chains,mte=True),
    }
    variants={}
    renamings={}
    for name in ('irregular','pressure','shared_input','direct_dependency'):
        g=copy.deepcopy(specs[name]); ids=[x['id'] for x in g['ops']+g['tensors']]
        new=rng.sample(range(10000,1000000),len(ids)); mapping=dict(zip(ids,new))
        for x in g['ops']+g['tensors']: x['id']=mapping[x['id']]
        for e in g['edges']: e['source']=mapping[e['source']]; e['target']=mapping[e['target']]
        for key in g: rng.shuffle(g[key])
        variants[name+'_relabel']=g; renamings[name+'_relabel']=mapping
    invalid={}
    for name in ('duplicate_id','negative_cycles','duplicate_edge','copy_cycle'):
        g=copy.deepcopy(specs['serial'])
        if name=='duplicate_id': g['ops'].append(copy.deepcopy(g['ops'][1]))
        if name=='negative_cycles': g['ops'][1]['cycles']=-1
        if name=='duplicate_edge': g['edges'].append(copy.deepcopy(g['edges'][0]))
        if name=='copy_cycle': g['edges'].append(dict(source=g['ops'][-1]['id'],target=g['tensors'][0]['id']))
        invalid[name]=g
    allgraphs={**specs,**variants,**invalid}
    jobs=[dict(name=name,file=name+'.json',cores=n,kind='base') for name in specs for n in (2,5)]
    jobs += [dict(name=name,file=name+'.json',cores=5,kind='relabel') for name in variants]
    jobs += [dict(name=name,file=name+'.json',cores=2,kind='invalid') for name in invalid]
    jobs += [dict(name='serial_alias',file='case_001.json',cores=5,kind='alias'),
             dict(name='serial_repeat',file='serial.json',cores=5,kind='repeat')]
    dump(ROOT/'protocol.json',dict(seed=SEED,base_graphs=list(specs),variants=list(variants),
        cores=[2,5],max_official_evaluations=80,solver_changes=False,
        metric='T_component / T_selected; not single-core speedup',
        note='Freeze all plans before any official evaluation. No tuning or retry selection.'))
    hashes={}
    for q,source,files in [
        (1,'q1_priority_20260926',['solver.py','baseline.py','q1_optimized.py','mechanistic.py','policy.json']),
        (2,'q2_priority_20260926/final_v2',['solver.py','baseline.py','q1_optimized.py','model.py','memory_proxy.py'])]:
        folder=ROOT/f'isolated_q{q}'; (folder/'inputs').mkdir(parents=True,exist_ok=True)
        for name in files:
            src=PROJECT/source/name; hashes[str(src.relative_to(PROJECT))]=sha(src)
            shutil.copy2(src,folder/name)
        shutil.copy2(PROJECT/'official/data/config.txt',folder/'config.txt')
        shutil.copy2(ROOT/'infer_worker.py',folder/'infer_worker.py')
        for name,g in allgraphs.items(): dump(folder/'inputs'/f'{name}.json',g)
        dump(folder/'inputs'/'case_001.json',specs['serial']); dump(folder/'jobs.json',jobs)
    dump(ROOT/'source_hashes.json',hashes); dump(ROOT/'renamings.json',renamings)
    return specs,variants,invalid


def main():
    specs,variants,invalid=prepare()
    for q in (1,2):
        f=ROOT/f'isolated_q{q}'
        run=subprocess.run([sys.executable,'-I',str(f/'infer_worker.py'),str(q)],cwd=f,
                           capture_output=True,text=True,timeout=90)
        (f/'worker.log').write_text(run.stdout+run.stderr,encoding='utf-8')
        if run.returncode: raise RuntimeError(run.stderr)
    # Inference is now complete. This phase alone imports the official evaluator.
    frozen={str(p.relative_to(ROOT)):sha(p) for p in ROOT.glob('isolated_*/inference.json')}
    dump(ROOT/'frozen_inference.json',frozen)
    sys.path.insert(0,str(PROJECT/'official/code'))
    from evaluation_validation import validate_graph, read_evaluation_config
    from multicore_cut_evaluate_problem_1 import evaluate_scene_a,read_scene_a_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b,read_scene_b_config
    cfg=PROJECT/'official/data/config.txt'; fixed=read_evaluation_config(str(cfg))
    ac=read_scene_a_config(str(cfg)); bc=read_scene_b_config(str(cfg))
    graph_checks={}
    for name,g in {**specs,**variants,**invalid}.items():
        try: validate_graph(g); graph_checks[name]={'valid':True}
        except Exception as exc: graph_checks[name]={'valid':False,'error':str(exc)}
    dump(ROOT/'graph_validation.json',graph_checks)
    assert all(graph_checks[n]['valid'] for n in [*specs,*variants])
    assert all(not graph_checks[n]['valid'] for n in invalid)
    rows=[]; inference={}; rename=json.loads((ROOT/'renamings.json').read_text())
    for q in (1,2):
        folder=ROOT/f'isolated_q{q}'
        data=json.loads((folder/'inference.json').read_text(encoding='utf-8')); inference[q]=data
        lookup={(r['name'],r['cores']):r for r in data['jobs']}
        for job in data['jobs']:
            if job['kind'] not in ('base','relabel'): continue
            g=json.loads((folder/'inputs'/job['file']).read_text())
            plans={'selected':job.get('plan')}
            if job['kind']=='base': plans['component']=job.get('component')
            else:
                original=lookup[(job['name'].replace('_relabel',''),5)]['plan']
                m=rename[job['name']]
                plans['transported_original']={'node_to_subgraph':{str(m[k]):v for k,v in original['node_to_subgraph'].items()},
                                               'core_schedules':original['core_schedules']}
            for label,plan in plans.items():
                row=dict(question=q,name=job['name'],cores=job['cores'],kind=job['kind'],plan=label,
                         inference_seconds=job['seconds'],selected=job.get('report',{}).get('selected'))
                start=time.perf_counter()
                try:
                    if plan is None: raise ValueError(job.get('error','no plan'))
                    if q==1: out=evaluate_scene_a(g,plan,**fixed,same_core_wait=ac['task_same_core_wait_cycles'],cross_core_wait=ac['task_cross_core_wait_cycles'])
                    else: out=evaluate_scene_b(g,plan,**fixed,cross_core_copy_delay=bc['cross_core_copy_delay_cycles'])
                    row.update(status='ok',makespan=out['makespan'],
                               spill_bytes=out['data_movement_bytes']['spill_added_copy_bytes'],
                               memory_peak=out['memory_peak_by_core'])
                    if any(v[r]>fixed['capacity'][r] for v in out['memory_peak_by_core'].values() for r in ('L1','UB')):
                        raise AssertionError('capacity violated')
                except Exception as exc: row.update(status='error',error=repr(exc))
                row['audit_seconds']=time.perf_counter()-start; rows.append(row)
                dump(ROOT/'official_results.json',rows)
    summaries={}
    for q,data in inference.items():
        selected=[r for r in rows if r['question']==q and r['plan']=='selected']
        ratios=[]; regress=[]; changed=[]
        for r in selected:
            ref=next(x for x in rows if x['question']==q and x['name']==r['name'] and x['cores']==r['cores'] and x['plan']!='selected')
            if r['status']=='ok' and ref['status']=='ok':
                if r['kind']=='base':
                    ratio=ref['makespan']/r['makespan']; ratios.append(ratio)
                    if ratio<1-1e-9: regress.append(dict(name=r['name'],cores=r['cores'],slowdown=r['makespan']/ref['makespan']-1))
                elif abs(r['makespan']-ref['makespan'])>1e-7:
                    changed.append(dict(name=r['name'],relative_to_transport=r['makespan']/ref['makespan']-1))
        base=next(r for r in data['jobs'] if r['name']=='serial' and r['cores']==5)
        summaries[str(q)]=dict(success=sum(r['status']=='ok' for r in selected),attempts=len(selected),
             mean_component_relative_efficiency=statistics.mean(ratios),regressions=regress,
             relabel_solver_effects=changed,
             inference_seconds_median=statistics.median(r['inference_seconds'] for r in selected),
             inference_seconds_max=max(r['inference_seconds'] for r in selected),
             filename_and_repeat_stable=all(r['plan']==base['plan'] for r in data['jobs'] if r['kind'] in ('alias','repeat')),
             illegal_inputs_accepted=[r['name'] for r in data['jobs'] if r['kind']=='invalid' and r['status']=='generated'],
             validator_checks=data['validator_checks'],official_modules=data['official_modules'],
             all_inputs_unchanged=all(r['input_unchanged'] for r in data['jobs']))
    manifest=json.loads((PROJECT/'official_manifest.json').read_text(encoding='utf-8'))
    unchanged=sum(sha(PROJECT/'official'/r['path'])==r['sha256'] for r in manifest['files'])
    source=json.loads((ROOT/'source_hashes.json').read_text())
    summary=dict(protocol=json.loads((ROOT/'protocol.json').read_text()),questions=summaries,
      official_calls=len(rows),official_files_unchanged=unchanged,official_files=len(manifest['files']),
      solver_sources_unchanged=all(sha(PROJECT/p)==h for p,h in source.items()),
      frozen_plans_unchanged=all(sha(ROOT/p)==h for p,h in frozen.items()),
      official_errors=[r for r in rows if r['status']!='ok'])
    dump(ROOT/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
