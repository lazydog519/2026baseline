"""Experiment orchestration, deliberately excluded from the inference package."""
import argparse
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor,as_completed
import csv
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from solver import SOURCES

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x): p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def generate_one(out,case,n):
    graph=PROJECT/'official/data'/f'{case}.json'
    plan=out/'plans'/f'{case}_n{n}.json'
    report=out/'plans'/f'{case}_n{n}_generation.json'
    start=time.perf_counter()
    result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'solver.py'),str(graph),
          '-n',str(n),'--config',str(PROJECT/'official/data/config.txt'),
          '-o',str(plan),'--report',str(report)],capture_output=True,text=True,
          encoding='utf-8',errors='replace',timeout=300)
    row=dict(case=case,cores=n,exit_code=result.returncode,seconds=time.perf_counter()-start,
             graph_sha256=sha(graph),error=result.stderr[-1000:])
    if result.returncode==0:
        row.update(plan_sha256=sha(plan),report_sha256=sha(report))
    return row


def generate(args,out):
    out.mkdir(parents=True,exist_ok=True)
    (out/'plans').mkdir(exist_ok=True)
    cases=args.cases or [f'case_{i:03d}' for i in range(1,101)]
    path=out/'generation_manifest.json'
    hashes={s:sha(ROOT/s) for s in SOURCES}
    official={str(p.relative_to(PROJECT/'official')):sha(p) for p in (PROJECT/'official').rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    if path.exists():
        if not args.resume: raise FileExistsError('output exists; use --resume')
        manifest=json.loads(path.read_text(encoding='utf-8'))
        if manifest['source_sha256']!=hashes: raise ValueError('frozen code changed')
        if manifest['official_sha256']!=official: raise ValueError('official attachment changed')
        if manifest['cases']!=cases or manifest['cores']!=args.cores:
            raise ValueError('cannot change frozen case/core scope')
    else:
        manifest=dict(version='q3-input-adaptive',cases=cases,cores=args.cores,
                      source_sha256=hashes,official_sha256=official,
                      generation='one fresh subprocess per input/core; no official evaluator',
                      jobs=[])
        save(path,manifest)
    rows={(r['case'],r['cores']):r for r in manifest['jobs']}
    todo=[]
    for case in cases:
        for n in args.cores:
            old=rows.get((case,n))
            plan=out/'plans'/f'{case}_n{n}.json'
            report=out/'plans'/f'{case}_n{n}_generation.json'
            if old and old['exit_code']==0 and plan.exists() and report.exists() and (
                    old['plan_sha256']==sha(plan) and old['report_sha256']==sha(report)
                    and old['graph_sha256']==sha(PROJECT/'official/data'/f'{case}.json')):
                continue
            todo.append((case,n))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending={pool.submit(generate_one,out,*key):key for key in todo}
        for f in as_completed(pending):
            case,n=pending[f]
            try: row=f.result()
            except Exception as exc: row=dict(case=case,cores=n,exit_code=1,error=repr(exc))
            rows[case,n]=row
            manifest['jobs']=[rows[k] for k in sorted(rows)]
            save(path,manifest)
            print('generated',case,n,row['exit_code'],flush=True)
    if any(r['exit_code'] for r in rows.values()): raise SystemExit('generation incomplete')


def evaluate_one(out,job):
    sys.path.insert(0,str(PROJECT/'official/code'))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b,read_scene_b_config
    from multicore_cut_evaluate_problem_3 import evaluate_problem_3,read_cache_config
    case,n=job['case'],job['cores']
    graph_path=PROJECT/'official/data'/f'{case}.json'
    plan_path=out/'plans'/f'{case}_n{n}.json'
    if sha(graph_path)!=job['graph_sha256'] or sha(plan_path)!=job['plan_sha256']:
        raise ValueError('frozen input/plan mismatch')
    graph=json.loads(graph_path.read_text(encoding='utf-8'))
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    cfgpath=str(PROJECT/'official/data/config.txt')
    cfg=read_evaluation_config(cfgpath)
    kwargs=dict(bandwidth=cfg['bandwidth'],capacity=cfg['capacity'],
                cross_core_copy_delay=read_scene_b_config(cfgpath)['cross_core_copy_delay_cycles'])
    folder=out/'results'/f'{case}_n{n}'
    folder.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter()
    plain=evaluate_scene_b(graph,plan,**kwargs)
    with gzip.open(folder/'no_l2.json.gz','wt',encoding='utf-8') as fp:
        json.dump(plain,fp,separators=(',',':'))
    a=plain['makespan']; ad=plain['data_movement_bytes']['added_copy_bytes']
    del plain
    cached=evaluate_problem_3(graph,plan,**kwargs,**read_cache_config(cfgpath))
    with gzip.open(folder/'l2.json.gz','wt',encoding='utf-8') as fp:
        json.dump(cached,fp,separators=(',',':'))
    row=dict(case=case,cores=n,status='ok',no_l2_cycles=a,l2_cycles=cached['makespan'],
             no_l2_added_bytes=ad,l2_added_bytes=cached['data_movement_bytes']['added_copy_bytes'],
             cache_hit_rate=cached['cache_stats']['hit_rate'],
             hit_bytes=cached['cache_stats']['hit_bytes'],miss_bytes=cached['cache_stats']['miss_bytes'],
             cache_gain=a/cached['makespan'],seconds=time.perf_counter()-start,
             plan_sha256=job['plan_sha256'])
    save(folder/'audit.json',row)
    return row


def audit(args,out):
    manifest=json.loads((out/'generation_manifest.json').read_text(encoding='utf-8'))
    for s,h in manifest['source_sha256'].items():
        if sha(ROOT/s)!=h: raise ValueError('inference code changed after plan freezing')
    for p,h in manifest['official_sha256'].items():
        if sha(PROJECT/'official'/p)!=h: raise ValueError('official file changed')
    if any(j['exit_code'] for j in manifest['jobs']): raise ValueError('failed generation')
    if len(manifest['jobs'])!=len(manifest['cases'])*len(manifest['cores']):
        raise ValueError('incomplete generation')
    progress=out/'progress.csv'
    fields=('case','cores','status','no_l2_cycles','l2_cycles','no_l2_added_bytes','l2_added_bytes',
            'cache_hit_rate','hit_bytes','miss_bytes','cache_gain','seconds','plan_sha256','error')
    rows={}
    if progress.exists():
        if not args.resume: raise FileExistsError('audit exists; use --resume')
        rows={(r['case'],int(r['cores'])):r for r in csv.DictReader(progress.open(encoding='utf-8'))
              if r['status']=='ok'}
    todo=[j for j in manifest['jobs'] if (j['case'],j['cores']) not in rows]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        pending={pool.submit(evaluate_one,out,j):j for j in todo}
        for future in as_completed(pending):
            j=pending[future]
            try: row=future.result()
            except Exception as exc: row=dict(case=j['case'],cores=j['cores'],status='error',error=repr(exc))
            rows[row['case'],int(row['cores'])]=row
            with progress.open('w',encoding='utf-8',newline='') as fp:
                writer=csv.DictWriter(fp,fields); writer.writeheader()
                writer.writerows({k:rows[key].get(k,'') for k in fields} for key in sorted(rows))
            print('audited',row['case'],row['cores'],row['status'],row.get('cache_gain'),flush=True)
    if len(rows)!=len(manifest['jobs']) or any(r['status']!='ok' for r in rows.values()):
        raise SystemExit('official acceptance incomplete')
    summarize(out)


def summarize(out):
    manifest=json.loads((out/'generation_manifest.json').read_text(encoding='utf-8'))
    rows=list(csv.DictReader((out/'progress.csv').open(encoding='utf-8')))
    reference={r['case']:float(r['singlecore_cycles']) for r in
               csv.DictReader((PROJECT/'final_metrics/per_case_metrics.csv').open(encoding='utf-8'))}
    q2={(r['case'],int(r['cores'])):float(r['makespan_cycles']) for r in
        csv.DictReader((PROJECT/'q2_priority_20260926/final_v2/full_metrics.csv').open(encoding='utf-8'))}
    metrics=[]
    for r in rows:
        if r['status']!='ok': continue
        case,n=r['case'],int(r['cores'])
        r.update(l2_speedup=reference[case]/float(r['l2_cycles']),
                 no_l2_speedup=reference[case]/float(r['no_l2_cycles']),
                 q2_cycles=q2.get((case,n),reference[case]),
                 vs_q2_gain=q2.get((case,n),reference[case])/float(r['l2_cycles']))
        metrics.append(r)
    if metrics:
        with (out/'metrics.csv').open('w',encoding='utf-8',newline='') as fp:
            w=csv.DictWriter(fp,list(metrics[0]));w.writeheader();w.writerows(metrics)
    by_core={}
    for n in manifest['cores']:
        group=[r for r in metrics if int(r['cores'])==n]
        by_core[str(n)]={k:statistics.mean(float(r[k]) for r in group)
                         for k in ('l2_speedup','no_l2_speedup','cache_gain','cache_hit_rate','vs_q2_gain',
                                   'l2_added_bytes','no_l2_added_bytes')}
        by_core[str(n)]['cases']=len(group)
    summary=dict(complete_cases=sum(all(any(r['case']==c and int(r['cores'])==n for r in metrics)
                                       for n in manifest['cores']) for c in manifest['cases']),
                 expected_jobs=len(manifest['cases'])*len(manifest['cores']),audited_jobs=len(metrics),
                 failed=len(rows)-len(metrics),mean_by_cores=by_core,
                 source_sha256=manifest['source_sha256'],official_files_unchanged=len(manifest['official_sha256']))
    save(out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('mode',choices=['generate','audit','summarize'])
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--cases',nargs='+')
    ap.add_argument('--cores',nargs='+',type=int,default=[1,2,3,4,5])
    ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--resume',action='store_true')
    a=ap.parse_args(); out=a.output.resolve()
    if a.mode=='generate': generate(a,out)
    elif a.mode=='audit': audit(a,out)
    else: summarize(out)
