"""Aggregate only Q2-final cold runs; the single-core reference is Q2 official data."""
import csv,json,statistics
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
RUNS=PKG/'results'/'runs'
REF=Path(__file__).resolve().parents[3]/'project'/'q2_cold'/'final'/'per_case_metrics.csv'
OUT=PKG/'results'
def main():
    ref={(r['case'],int(r['cores'])):r for r in csv.DictReader(REF.open(encoding='utf-8'))}
    (OUT/'singlecore_reference.csv').write_text('case,singlecore_cycles\n'+'\n'.join(f'{case},{int(float(ref[case,2]["singlecore_cycles"]))}' for case in sorted({k[0] for k in ref}))+'\n',encoding='utf-8')
    rows=[]; failures=[]
    for i in range(1,101):
      case=f'case_{i:03d}'
      for n in range(2,6):
        d=RUNS/case/f'n{n}'
        if not (d/'run.json').is_file(): failures.append([case,n,'missing']); continue
        run=json.loads((d/'run.json').read_text(encoding='utf-8'))
        process=json.loads((d/'process.json').read_text(encoding='utf-8'))
        if process.get('returncode')!=0: failures.append([case,n,'returncode']); continue
        events=[json.loads(s) for s in (d/'search.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
        evals=[e for e in events if e.get('event')=='evaluation' and e.get('status')=='ok']
        accepted=[e for e in evals if e.get('accepted')]
        selected=accepted[-1] if accepted else evals[0]
        one=int(float(ref[case,n]['singlecore_cycles']))
        init=int(run['initial_cycles']); final=int(run['makespan_cycles'])
        rows.append(dict(case=case,cores=n,singlecore_cycles=one,initial_cycles=init,makespan_cycles=final,
          initial_speedup=one/init,speedup=one/final,reduction_percent=100*(init-final)/init,
          added_copy_bytes=int(run['added_copy_bytes']),spill_bytes=int(selected.get('spill_bytes',0)),
          peak_l1_bytes=int(selected.get('peak_l1_bytes',0)),peak_ub_bytes=int(selected.get('peak_ub_bytes',0)),
          locality_ratio=float(selected.get('locality_ratio',0)),internalized_bytes=int(selected.get('internalized_bytes',0)),
          buffer85_ok=bool(selected.get('buffer85_ok',False)),evaluations=int(run['evaluations']),
          wall_seconds=float(process['process_wall_s']),selected=run.get('selected','')))
    if failures: raise SystemExit('Incomplete/failed jobs: '+str(failures[:10])+f' ({len(failures)} total)')
    rows.sort(key=lambda r:(r['case'],r['cores']))
    with (OUT/'per_case_metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    aggregate={'schema':'q2-cilc-v1','complete_cases':len({r['case'] for r in rows}),'selected_jobs':len(rows),
      'cold_start':True,'q1_results_read':False,'locality_target':0.85,
      'mean_speedup':{str(n):statistics.mean(r['speedup'] for r in rows if r['cores']==n) for n in range(2,6)},
      'initial_mean_speedup':{str(n):statistics.mean(r['initial_speedup'] for r in rows if r['cores']==n) for n in range(2,6)},
      'improved_vs_initial':{str(n):sum(r['makespan_cycles']<r['initial_cycles'] for r in rows if r['cores']==n) for n in range(2,6)},
      'median_wall_seconds':{str(n):statistics.median(r['wall_seconds'] for r in rows if r['cores']==n) for n in range(2,6)},
      'total_evaluations':sum(r['evaluations'] for r in rows),
      'mean_locality_ratio':{str(n):statistics.mean(r['locality_ratio'] for r in rows if r['cores']==n) for n in range(2,6)},
      'buffer85_ok_cases':{str(n):sum(r['buffer85_ok'] for r in rows if r['cores']==n) for n in range(2,6)},
      'total_spill_bytes':{str(n):sum(r['spill_bytes'] for r in rows if r['cores']==n) for n in range(2,6)},
      'official_evaluated':True,'official_evaluator':'unchanged problem-2 evaluator; each selected plan accepted only from official simulation',
      'singlecore_reference':'results/singlecore_reference.csv; copied from Q2 cold single-core official evaluations; no Q1 outputs read'}
    (OUT/'aggregate.json').write_text(json.dumps(aggregate,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(aggregate,indent=2,ensure_ascii=False))
if __name__=='__main__': main()
