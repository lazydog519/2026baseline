import json,shutil,hashlib
from pathlib import Path
root=Path('project').resolve();out=root/'q2_incremental_20260925'; metrics={(r['case'],int(r['cores'])):r for r in __import__('csv').DictReader((out/'final_per_case_metrics.csv').open())}; files=[]
for i in range(1,101):
 case=f'case_{i:03d}'
 for n in range(2,6):
  dst=out/'final_plans'/case/f'n{n}';dst.mkdir(parents=True,exist_ok=True); dest=dst/f'{case}_multicore_res.json'
  r=metrics[(case,n)]
  if r['selected']=='cold':src=root/'q2_cold'/'full'/case/f'n{n}'/f'{case}_multicore_res.json'
  else:src=out/'selected_plans'/case/f'n{n}'/'plan.json'
  shutil.copyfile(src,dest);data=json.loads(dest.read_text())
  if set(data)!={'node_to_subgraph','core_schedules'}:raise ValueError(f'output schema {case} n{n}: {set(data)}')
  files.append({'path':str(dest.relative_to(root)),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'case':case,'cores':n,'source':r['selected']})
(out/'final_plan_manifest.json').write_text(json.dumps({'schema':'q2-incremental-final-plan-v1','count':len(files),'plans':files},ensure_ascii=False,indent=2)+'\n')
print('final_plans',len(files),'bytes',sum((out/f['path'].replace('q2_incremental_20260925/','')).stat().st_size for f in files))
