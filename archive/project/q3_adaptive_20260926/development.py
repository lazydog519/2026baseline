"""Development only. Candidate freezing, official labels, one global correction."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import csv
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

from solver import InputGraph,hardware,candidates,SOURCES

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x): p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def build(case):
    path=PROJECT/'official/data'/f'{case}.json'
    cfg=hardware(PROJECT/'official/data/config.txt')
    start=time.perf_counter()
    g,rows,rejected=candidates(json.loads(path.read_text(encoding='utf-8')),5,cfg)
    out=ROOT/'development'/case
    out.mkdir(parents=True,exist_ok=True)
    for row in rows:
        target=out/f"{row['name']}.json"
        save(target,row.pop('plan'))
        row.update(case=case,cores=5,plan=str(target.relative_to(ROOT)),file_sha256=digest(target))
    save(out/'generation.json',dict(case=case,profile=g.profile,candidates=rows,rejected=rejected,
                                   seconds=time.perf_counter()-start,graph_sha256=digest(path)))


def prepare():
    profiles=[]
    cfg=hardware(PROJECT/'official/data/config.txt')
    for p in sorted((PROJECT/'official/data').glob('case_*.json')):
        g=InputGraph(json.loads(p.read_text(encoding='utf-8')),5,cfg)
        profiles.append(dict(case=p.stem,graph_sha256=digest(p),**g.profile))
    save(ROOT/'input_profiles.json',profiles)
    bins={}
    for row in profiles:
        # Limit development cost by size; largest graphs remain in full testing.
        if row['ops']>5000: continue
        size=0 if row['ops']<=256 else 1 if row['ops']<=1024 else 2
        key=(row['components']==1,size)
        bins.setdefault(key,[]).append(row)
    train,confirm=[],[]
    for key,rows in sorted(bins.items()):
        rows=sorted(rows,key=lambda r:hashlib.sha256(('20260926'+r['graph_sha256']).encode()).hexdigest())
        train.extend(r['case'] for r in rows[:1])
        confirm.extend(r['case'] for r in rows[1:2])
    save(ROOT/'development_split.json',dict(development=train,confirmation=confirm,
         selection='graph size/components and fixed hash; no score-based sample choice',
         boundary='previous iterations have seen the given dataset; confirmation is iteration-specific'))
    for case in train:
        subprocess.run([sys.executable,'-X','utf8',str(__file__),'build','--case',case],check=True)
    jobs=[]
    for case in train:
        jobs.extend(json.loads((ROOT/'development'/case/'generation.json').read_text(encoding='utf-8'))['candidates'])
    save(ROOT/'development_manifest.json',dict(jobs=jobs,source_sha256={s:digest(ROOT/s) for s in SOURCES}))
    print(json.dumps(dict(train=train,confirm=confirm,candidates=len(jobs))))


def official(job):
    sys.path.insert(0,str(PROJECT/'official/code'))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_3 import evaluate_problem_3,read_scene_b_config,read_cache_config
    graph_path=PROJECT/'official/data'/f"{job['case']}.json"
    plan_path=ROOT/job['plan']
    if digest(plan_path)!=job['file_sha256']: raise ValueError('frozen plan changed')
    graph=json.loads(graph_path.read_text(encoding='utf-8'))
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    path=str(PROJECT/'official/data/config.txt')
    cfg=read_evaluation_config(path)
    start=time.perf_counter()
    result=evaluate_problem_3(graph,plan,bandwidth=cfg['bandwidth'],capacity=cfg['capacity'],
              cross_core_copy_delay=read_scene_b_config(path)['cross_core_copy_delay_cycles'],
              **read_cache_config(path))
    return dict(case=job['case'],name=job['name'],status='ok',
                makespan=result['makespan'],extra_bytes=result['data_movement_bytes']['added_copy_bytes'],
                hit_rate=result['cache_stats']['hit_rate'],seconds=time.perf_counter()-start)


def evaluate(workers):
    manifest=json.loads((ROOT/'development_manifest.json').read_text())
    for s,h in manifest['source_sha256'].items():
        if digest(ROOT/s)!=h: raise ValueError('source changed after freezing candidates')
    target=ROOT/'development_labels.json'
    rows=json.loads(target.read_text()) if target.exists() else []
    done={(r['case'],r['name']) for r in rows if r['status']=='ok'}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending={pool.submit(official,j):j for j in manifest['jobs'] if (j['case'],j['name']) not in done}
        for future in as_completed(pending):
            j=pending[future]
            try: row=future.result()
            except Exception as exc: row=dict(case=j['case'],name=j['name'],status='error',error=repr(exc))
            rows=[r for r in rows if (r['case'],r['name'])!=(j['case'],j['name'])]
            rows.append(row); save(target,rows)
            print(row['case'],row['name'],row['status'],row.get('makespan'),flush=True)


def calibrate():
    jobs=json.loads((ROOT/'development_manifest.json').read_text())['jobs']
    labels={(r['case'],r['name']):r for r in json.loads((ROOT/'development_labels.json').read_text())}
    if len(labels)!=len(jobs) or any(r['status']!='ok' for r in labels.values()):
        raise ValueError('development evaluations incomplete')
    groups={}
    for j in jobs:
        row=dict(j,actual=labels[j['case'],j['name']]['makespan'])
        groups.setdefault(j['case'],[]).append(row)
    # A finite scalar sensitivity check, reusing frozen official labels.
    # This does not launch candidate search or another official evaluation.
    trials=[]
    for weight in (0.,0.25,0.5,1.,2.,4.):
        ratios=[]
        selected=[]
        for case,rows in groups.items():
            winner=min(rows,key=lambda r:(r['event_cycles']+weight*r['spill_cycles'],
                                          r['projected_copy_bytes'],r['name']))
            best=min(r['actual'] for r in rows)
            ratios.append(winner['actual']/best)
            selected.append(dict(case=case,name=winner['name'],actual=winner['actual'],
                                 best_candidate=best))
        trials.append(dict(weight=weight,mean_candidate_regret=statistics.mean(ratios)-1,
                           selected=selected))
    best=min(trials,key=lambda r:(r['mean_candidate_regret'],abs(r['weight']-1)))
    policy=json.loads((ROOT/'policy.json').read_text())
    policy.update(version='q3-adaptive-v1-frozen',spill_weight=best['weight'],
                  coefficient_origin='one global overlap correction chosen using current development labels')
    save(ROOT/'policy.json',policy)
    save(ROOT/'calibration.json',dict(trials=trials,chosen_weight=best['weight'],
         warning='development samples are reused for calibration; no claim of independent test performance'))
    print(json.dumps(dict(weight=best['weight'],regret=best['mean_candidate_regret'],
                          cases=len(groups),labels=len(labels))))


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('mode',choices=['prepare','build','evaluate','calibrate'])
    ap.add_argument('--case')
    ap.add_argument('--workers',type=int,default=4)
    a=ap.parse_args()
    if a.mode=='prepare': prepare()
    elif a.mode=='build': build(a.case)
    elif a.mode=='evaluate': evaluate(a.workers)
    else: calibrate()
