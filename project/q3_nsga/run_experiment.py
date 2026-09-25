"""Frozen equal-budget three-method test, independent processes, official audit."""
import concurrent.futures
import csv
import gzip
import hashlib
import json
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pymoo
from solve import ROOT,P,fp
from evaluation_validation import read_evaluation_config
from multicore_cut_evaluate_problem_3 import evaluate_problem_3,read_cache_config,read_scene_b_config
from multicore_cut_evaluate_problem_2 import evaluate_scene_b


def main():
    cfg=json.loads((ROOT/'experiment.json').read_text())
    files=[ROOT/'solve.py',ROOT/'experiment.json',P/'q3_design/q3_pilot_solver.py',
           P/'solution/baseline.py',P/'solution/q1_optimized.py']
    frozen={str(f.relative_to(P)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    manifest=dict(frozen_utc=datetime.now(timezone.utc).isoformat(),files=frozen,
                  pymoo=pymoo.__version__,numpy=np.__version__,scope=cfg['scope'])
    out=ROOT/'experiment';out.mkdir(exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    hw=read_evaluation_config(str(P/'official/data/config.txt'))
    sc=read_scene_b_config(str(P/'official/data/config.txt'))
    kw=dict(bandwidth=hw['bandwidth'],capacity=hw['capacity'],cross_core_copy_delay=sc['cross_core_copy_delay_cycles'])
    cache=read_cache_config(str(P/'official/data/config.txt'))
    def job(case,n,method,seed):
        dest=out/case/f'n{n}'/method/f'seed_{seed}';dest.mkdir(parents=True,exist_ok=True)
        graph_path=P/f'official/data/{case}.json'
        with (dest/'console.log').open('w',encoding='utf-8') as stream:
            proc=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'solve.py'),str(graph_path),
                '-n',str(n),'--method',method,'--seed',str(seed),'--output',str(dest)],
                stdout=stream,stderr=subprocess.STDOUT)
        if proc.returncode:raise RuntimeError(f'{case}/{method}/{seed}: inspect console.log')
        summary=json.loads((dest/'run.json').read_text());g=json.loads(graph_path.read_text())
        plan=json.loads((dest/'plan.json').read_text())
        assert set(plan)=={'node_to_subgraph','core_schedules'}
        with gzip.open(dest/'result.json.gz','rt') as f:stored=json.load(f)
        result=evaluate_problem_3(g,plan,**kw,**cache)
        assert json.loads(json.dumps(result))==stored
        paired=evaluate_scene_b(g,plan,**kw)
        assert result['data_movement_bytes']==paired['data_movement_bytes']
        with gzip.open(dest/'paired_no_l2.json.gz','wt') as f:json.dump(paired,f,separators=(',',':'))
        return dict(case=case,cores=n,method=method,seed=seed,makespan=result['makespan'],
            construction_best=summary['construction_best'],construction_ratio=summary['improvement_ratio'],
            no_l2_same_plan=paired['makespan'],same_plan_cache_ratio=paired['makespan']/result['makespan'],
            added_copy_bytes=summary['added_copy_bytes'],cache_miss_bytes=summary['cache_miss_bytes'],
            hit_rate=summary['hit_rate'],official_calls=summary['official_calls'],
            invalid=summary['invalid_records'],seconds=summary['elapsed_seconds'],
            rechecked=True,initial_population_hashes=summary['initial_population_hashes'])
    jobs=[(c,n,m,s) for c in cfg['cases'] for n in cfg['cores'] for s in cfg['seeds'] for m in cfg['methods']]
    rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg['workers']) as pool:
        for future in concurrent.futures.as_completed([pool.submit(job,*jobargs) for jobargs in jobs]):
            row=future.result();rows.append(row);rows.sort(key=lambda r:(r['case'],r['cores'],r['seed'],r['method']))
            with (out/'metrics.csv').open('w',newline='',encoding='utf-8') as f:
                fields=[k for k in rows[0] if k!='initial_population_hashes']
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in rows)
            print(row['case'],row['method'],row['seed'],row['makespan'],flush=True)
    for c in cfg['cases']:
        for n in cfg['cores']:
            for seed in cfg['seeds']:
                group=[r for r in rows if (r['case'],r['cores'],r['seed'])==(c,n,seed)]
                assert all(r['initial_population_hashes']==group[0]['initial_population_hashes'] for r in group)
                assert all(r['official_calls']==cfg['official_budget'] for r in group),'Budget was not filled'
    for f in files:assert hashlib.sha256(f.read_bytes()).hexdigest()==frozen[str(f.relative_to(P))]
    original=json.loads((P/'official_manifest.json').read_text(encoding='utf-8'))
    for e in original['files']:assert hashlib.sha256((P/'official'/e['path']).read_bytes()).hexdigest()==e['sha256']
    (out/'verification.json').write_text(json.dumps(dict(completed_jobs=len(rows),equal_initial_populations=True,
        equal_official_budgets=True,all_full_results_rechecked=True,official_files_unchanged=len(original['files']),
        frozen_sources_unchanged=True,no_full_100_case_run=True),indent=2)+'\n')


if __name__=='__main__':main()
