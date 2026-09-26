"""Independent per-case process runner; scores are read only after solving."""
import argparse
import concurrent.futures
import csv
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--sample',choices=['development','confirmation','full'],default='development')
    ap.add_argument('--cases',nargs='+',type=int)
    ap.add_argument('--cores',nargs='+',type=int,default=[5])
    ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--config',type=Path)
    ap.add_argument('--resume',action='store_true',help='Skip only complete matching experiment records; incomplete solver calls restart cold.')
    a=ap.parse_args();p=a.project.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    config=(a.config or p/'solution/q1_cold_config.json').resolve()
    params=json.loads(config.read_text(encoding='utf-8'))
    frozen=json.loads((p/'q1_cold/frozen_manifest.json').read_text(encoding='utf-8'))
    for name,digest in frozen['files'].items():
        assert hashlib.sha256((p/'solution'/name).read_bytes()).hexdigest()==digest,'frozen solver changed'
    samples=json.loads((p/'q1_cold/sampling.json').read_text(encoding='utf-8'))
    cases=([f'case_{i:03d}' for i in a.cases] if a.cases else
           [f'case_{i:03d}' for i in range(1,101)] if a.sample=='full' else samples[a.sample])
    (out/'experiment.json').write_text(json.dumps(dict(cases=cases,cores=a.cores,workers=a.workers,
        search_config=params,sample=a.sample),indent=2)+'\n',encoding='utf-8')
    ref={(r['case'],int(r['cores'])):r for r in csv.DictReader((p/'final_metrics/per_case_metrics.csv').open(encoding='utf-8'))}
    def job(case,n):
        d=out/case/f'n{n}';d.mkdir(parents=True,exist_ok=True)
        command=[sys.executable,'-X','utf8',str(p/'solution/q1_cold.py'),str(p/f'official/data/{case}.json'),
                 '-n',str(n),'--search-config',str(config),'-o',str(d/f'{case}_multicore_res.json'),'--trace-dir',str(d)]
        reusable=False
        required=['process.json','run.json','official_result.json.gz',f'{case}_multicore_res.json','search.jsonl']
        if a.resume and all((d/f).is_file() for f in required):
            process=json.loads((d/'process.json').read_text(encoding='utf-8'))
            run=json.loads((d/'run.json').read_text(encoding='utf-8'))
            plan=json.loads((d/f'{case}_multicore_res.json').read_text(encoding='utf-8'))
            graph=json.loads((p/f'official/data/{case}.json').read_text(encoding='utf-8'))
            reusable=(process['returncode']==0 and process['case']==case and process['cores']==n and
                run['search_config']==params and run['cores']==n and run['cold_start'] and not run['history_read'] and
                run['config_sha256']==hashlib.sha256((p/'official/data/config.txt').read_bytes()).hexdigest() and
                run['graph_sha256']==hashlib.sha256(json.dumps(graph,sort_keys=True).encode()).hexdigest() and
                run['selected_fingerprint']==hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        if not reusable:
            start=time.perf_counter()
            with (d/'console.log').open('w',encoding='utf-8') as stream:r=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT)
            process=dict(returncode=r.returncode,process_wall_s=time.perf_counter()-start,case=case,cores=n)
            (d/'process.json').write_text(json.dumps(process,indent=2)+'\n',encoding='utf-8')
            if r.returncode:return process
        run=json.loads((d/'run.json').read_text(encoding='utf-8'));base=ref[case,n]
        return dict(**process,already_completed=reusable,makespan_cycles=run['makespan_cycles'],initial_cycles=run['initial_cycles'],
                    singlecore_cycles=int(float(base['singlecore_cycles'])),
                    speedup=float(base['singlecore_cycles'])/run['makespan_cycles'],
                    component_baseline_cycles=int(float(base['q1_cycles'])),
                    baseline_speedup=float(base['singlecore_cycles'])/float(base['q1_cycles']),
                    selected=run['selected'],evaluations=run['evaluations'],added_copy_bytes=run['added_copy_bytes'])
    rows=[];failed=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(job,c,n) for c in cases for n in a.cores]
        for f in concurrent.futures.as_completed(futures):
            r=f.result();print(r['case'],r['cores'],r['returncode'],r.get('makespan_cycles'),round(r['process_wall_s'],2),flush=True)
            if r['returncode']:failed.append(r);continue
            rows.append(r);rows.sort(key=lambda x:(x['case'],x['cores']))
            with (out/'progress.csv').open('w',encoding='utf-8',newline='') as s:
                w=csv.DictWriter(s,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary=dict(expected_jobs=len(cases)*len(a.cores),finished_jobs=len(rows),failed=failed,
        means={n:statistics.mean(r['speedup'] for r in rows if r['cores']==n) for n in a.cores},
        baseline_means={n:statistics.mean(r['baseline_speedup'] for r in rows if r['cores']==n) for n in a.cores},
        official_evaluations=sum(r['evaluations'] for r in rows),total_solver_process_seconds=sum(r['process_wall_s'] for r in rows),
        resumed_complete_jobs=sum(r['already_completed'] for r in rows),
        new_official_evaluations=sum(r['evaluations'] for r in rows if not r['already_completed']),
        scope='These means describe this listed sample only, unless all 100 cases were run.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary),flush=True)
    if failed:raise SystemExit(1)


if __name__=='__main__':main()
