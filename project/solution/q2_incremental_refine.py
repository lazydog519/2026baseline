#!/usr/bin/env python3
"""Refine only winning neighboring widths from cached Q2 band search."""
import argparse, csv, json, sys, time, traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

def init(project):
    sys.path.insert(0, str(project / 'solution'))
    sys.path.insert(0, str(project / 'official' / 'code'))

def worker(task):
    project=Path(task['project']); case=task['case']; cores=int(task['cores']); active=int(task['active']); width=int(task['width'])
    init(project)
    from q1_optimized import active_core_plan, depth_band_plan
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config
    graph=json.loads((project/'official'/'data'/f'{case}.json').read_text())
    cfg=project/'official'/'data'/'config.txt'; settings=read_evaluation_config(str(cfg)); scene=read_scene_b_config(str(cfg))
    plan=active_core_plan(lambda g,n: depth_band_plan(g,n,width,data_aware=False),graph,cores,active)
    started=time.perf_counter()\n    result=evaluate_scene_b(graph,plan,bandwidth=settings['bandwidth'],capacity=settings['capacity'],cross_core_copy_delay=scene['cross_core_copy_delay_cycles'])
    return {'case':case,'cores':cores,'active_cores':active,'band_width':width,'status':'ok','makespan_cycles':result['makespan'],'added_copy_bytes':result['data_movement_bytes']['added_copy_bytes'],'partition_added_copy_bytes':result['data_movement_bytes']['partition_added_copy_bytes'],'spill_added_copy_bytes':result['data_movement_bytes']['spill_added_copy_bytes'],'peak_l1_bytes':max((p['L1'] for p in result['memory_peak_by_core'].values()),default=0),'peak_ub_bytes':max((p['UB'] for p in result['memory_peak_by_core'].values()),default=0),'wall_seconds':round(time.perf_counter()-started,3),'plan':plan,'result':result}

def main():
 p=argparse.ArgumentParser(); p.add_argument('--project',type=Path,required=True); p.add_argument('--out',type=Path,required=True); p.add_argument('--workers',type=int,default=3); p.add_argument('--dry-run',action='store_true'); a=p.parse_args(); project=a.project.resolve(); out=a.out.resolve(); out.mkdir(parents=True,exist_ok=True)
 summary=project/'q2_optimization'/'band'/'candidate_summary.csv'; metrics=project/'q2_cold'/'final'/'per_case_metrics.csv'
 rows=list(csv.DictReader(summary.open()))
 transfer=project/'q2_optimization'/'transfer'/'candidate_summary.csv'
 for r in csv.DictReader(transfer.open()):
  src=r.get('source_strategy','')
  if src.startswith('band_w'):
   parts=src.replace('band_w','').replace('_k',' ').split()
   r['strategy']=src; r['band_width']=parts[0]; r['active_cores']=parts[1]; rows.append(r)
 cold={(r['case'],int(r['cores'])):r for r in csv.DictReader(metrics.open())}
 best={}
 for r in rows:
  if r['status']!='ok' or not r['strategy'].startswith('band_w'): continue
  key=(r['case'],int(r['cores'])); k=int(r['active_cores']); n=key[1]
  if k>n or k<2: continue
  c=cold.get(key)
  if not c: continue
  score=(int(r['makespan_cycles']),int(r['added_copy_bytes']))
  old=(int(c['makespan_cycles']),int(c['added_copy_bytes']))
  if score<old and (key not in best or score<best[key][0]): best[key]=(score,r)
 tasks=[]
 for (case,cores),(score,row) in sorted(best.items()):
  w=int(row['band_width']); active=int(row['active_cores'])
  for nw in sorted(set([max(1,w-1),w+1])):
   tasks.append({'project':str(project),'case':case,'cores':cores,'active':active,'width':nw,'seed_width':w,'seed_score':score})
 manifest={'schema':'q2-incremental-refine-v1','source_search':'project/q2_optimization/band/candidate_summary.csv','baseline':'project/q2_cold/final/per_case_metrics.csv','seed_pairs':len(best),'candidate_count':len(tasks),'workers':a.workers,'tasks':tasks}
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 if a.dry_run:
  print(json.dumps({'seed_pairs':len(best),'candidate_count':len(tasks),'examples':tasks[:8]},ensure_ascii=False)); return
 done=[]
 with ProcessPoolExecutor(max_workers=a.workers) as pool:
  futs={pool.submit(worker,t):t for t in tasks}
  for f in as_completed(futs):
   t=futs[f]
   try:
    r=f.result(); d={k:v for k,v in r.items() if k not in ('plan','result')}; d.update(seed_width=t['seed_width'],seed_makespan=t['seed_score'][0]);
    folder=out/r['case']/f"n{r['cores']}"/f"w{r['band_width']}"; folder.mkdir(parents=True,exist_ok=True)
    (folder/'plan.json').write_text(json.dumps(r['plan'],separators=(',',':'))+'\n')
    import gzip
    with gzip.open(folder/'result.json.gz','wt',encoding='utf-8',compresslevel=1) as z: json.dump(r['result'],z,separators=(',',':'))
    d['candidate_dir']=str(folder.relative_to(out)); d['status']='ok'
   except Exception as e: d={'case':t['case'],'cores':t['cores'],'active_cores':t['active'],'band_width':t['width'],'seed_width':t['seed_width'],'status':'error','error':repr(e),'traceback':traceback.format_exc()[-2000:]}
   done.append(d); print(json.dumps(d,ensure_ascii=False),flush=True)
   fields=sorted(set().union(*(x.keys() for x in done)))
   with (out/'candidate_results.csv.tmp').open('w',newline='',encoding='utf-8') as fcsv:
    wri=csv.DictWriter(fcsv,fieldnames=fields); wri.writeheader(); wri.writerows(done)
   (out/'candidate_results.csv.tmp').replace(out/'candidate_results.csv')
 print(f'COMPLETE {len(done)}/{len(tasks)}')
if __name__=='__main__': main()
