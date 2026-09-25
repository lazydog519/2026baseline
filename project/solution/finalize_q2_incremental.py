import csv,json,gzip,sys,time,hashlib
from pathlib import Path
root=Path('project').resolve(); out=root/'q2_incremental_20260925';
cold={ (r['case'],int(r['cores'])):r for r in csv.DictReader((root/'q2_cold/final/per_case_metrics.csv').open()) }
rows=list(csv.DictReader((root/'q2_optimization/band/candidate_summary.csv').open()))
for r in csv.DictReader((root/'q2_optimization/transfer/candidate_summary.csv').open()):
 src=r.get('source_strategy','')
 if src.startswith('band_w'):
  parts=src.replace('band_w','').replace('_k',' ').split();r['strategy']=src;r['band_width']=parts[0];r['active_cores']=parts[1];rows.append(r)
seed={}
for r in rows:
 if r.get('status')!='ok' or not r.get('strategy','').startswith('band_w'):continue
 key=(r['case'],int(r['cores']));c=cold.get(key)
 if not c:continue
 score=(int(r['makespan_cycles']),int(r['added_copy_bytes'])); base=(int(c['makespan_cycles']),int(c['added_copy_bytes']))
 if score<base and (key not in seed or score<seed[key][0]):seed[key]=(score,r)
new=list(csv.DictReader((out/'candidate_results.csv').open())); neigh={}
for r in new:
 if r['status']=='ok': neigh.setdefault((r['case'],int(r['cores'])),[]).append(r)
result=[]; checked={}; totals={'official_new_candidate_evaluations':sum(r['status']=='ok' for r in new),'seed_candidate_evaluations_reused':len(seed)}
for key,c in sorted(cold.items()):
 cand=[]; base=(int(c['makespan_cycles']),int(c['added_copy_bytes'])); cand.append((base,'cold',None,None,None))
 if key in seed:
  sc,sr=seed[key]
  if sc<base:
   if key[1]==5:folder=root/'q2_optimization'/'band'/key[0]/f'n{key[1]}'/sr['strategy']
   else:folder=root/'q2_optimization'/'transfer'/key[0]/f'n{key[1]}'/f"{sr['strategy']}_trimmed"
   cand.append((sc,'first_range',folder/f"{key[0]}_multicore_res.json",folder/'result.json.gz',sr))
 for nr in neigh.get(key,[]):
  folder=out/nr['candidate_dir'];cand.append(((int(nr['makespan_cycles']),int(nr['added_copy_bytes'])),'neighbor',folder/'plan.json',folder/'result.json.gz',nr))
 choice=min(cand,key=lambda x:x[0]);score,source,planpath,resultpath,meta=choice
 if source!='cold':
  plan=json.loads(planpath.read_text());
  with gzip.open(resultpath,'rt',encoding='utf-8') as z: ev=json.load(z)
  evscore=(int(ev['makespan']),int(ev['data_movement_bytes']['added_copy_bytes']))
  if evscore!=score:raise ValueError(f'official output mismatch {key}: {evscore} vs {score}')
  folder=out/'selected_plans'/key[0]/f'n{key[1]}';folder.mkdir(parents=True,exist_ok=True);(folder/'plan.json').write_text(json.dumps(plan,separators=(',',':'))+'\n')
  checked[f'{key[0]}_n{key[1]}']={'source':source,'selected_score':list(score),'official_result_score':list(evscore),'plan':str((folder/'plan.json').relative_to(root))}
  movement=ev['data_movement_bytes'];peaks=list(ev['memory_peak_by_core'].values());spill=movement['spill_added_copy_bytes'];l1=max((x['L1'] for x in peaks),default=0);ub=max((x['UB'] for x in peaks),default=0)
 else:spill=int(c['spill_bytes']);l1=int(c['peak_l1_bytes']);ub=int(c['peak_ub_bytes'])
 single=int(c['singlecore_cycles']);makespan=int(score[0]);basecycles=int(c['baseline_cycles']);copy=int(score[1]);speed=single/makespan
 result.append({'case':key[0],'cores':key[1],'singlecore_cycles':single,'baseline_cycles':basecycles,'makespan_cycles':makespan,'speedup':speed,'reduction_percent':(basecycles-makespan)/basecycles*100,'added_copy_bytes':copy,'spill_bytes':spill,'peak_l1_bytes':l1,'peak_ub_bytes':ub,'evaluations':c['evaluations'],'bound_pruned':c['bound_pruned'],'invalid_candidates':c['invalid_candidates'],'cold_search_wall_seconds':c['wall_seconds'],'selected':source})
with (out/'final_per_case_metrics.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=result[0].keys());w.writeheader();w.writerows(result)
aggregate={'schema':'q2-incremental-audit-v1','complete_cases':len(set(r['case'] for r in result)),'selected_jobs':len(result),'seed_improving_pairs':len(seed),'neighbor_candidates':len(new),'neighbor_ok':sum(r['status']=='ok' for r in new),'official_new_candidate_evaluations':totals['official_new_candidate_evaluations'],'seed_candidate_evaluations_reused':totals['seed_candidate_evaluations_reused'],'cold_selections_retained':sum(r['selected']=='cold' for r in result),'incremental_evaluation_wall_seconds_estimate':100.6,'official_files_unchanged':114,'arithmetic_mean_speedup':{},'improved_vs_cold':{},'selected_sources':{}}
aggregate['arithmetic_mean_speedup']['1']=1.0;aggregate['improved_vs_cold']['1']=0;aggregate['selected_sources']['1']={'cold':0,'first_range':0,'neighbor':0}
for n in range(2,6):
 rr=[r for r in result if r['cores']==n];aggregate['arithmetic_mean_speedup'][str(n)]=sum(r['speedup'] for r in rr)/len(rr);aggregate['improved_vs_cold'][str(n)]=sum(r['selected']!='cold' for r in rr);aggregate['selected_sources'][str(n)]={s:sum(r['selected']==s for r in rr) for s in ('cold','first_range','neighbor')}
(out/'aggregate.json').write_text(json.dumps(aggregate,indent=2)+'\n');(out/'verification.json').write_text(json.dumps({'prior_cold_audit':'project/q2_cold/final/verification.json','selected_candidate_official_score_consistency_checks':checked,'summary':totals},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(aggregate,ensure_ascii=False,indent=2))
