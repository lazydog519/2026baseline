"""Small independent-process pilot with paired original evaluators."""
import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

P=Path(__file__).resolve().parents[1];ROOT=Path(__file__).parent
sys.path.insert(0,str(P/'official/code'))
from evaluation_validation import read_evaluation_config
from multicore_cut_evaluate_problem_3 import evaluate_problem_3,read_cache_config,read_scene_b_config
from multicore_cut_evaluate_problem_2 import evaluate_scene_b


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--phase',choices=['development','confirmation','diagnostic'],required=True)
    a=ap.parse_args();spec=json.loads((ROOT/'pilot_selection.json').read_text());out=ROOT/a.phase;out.mkdir(exist_ok=True)
    names=['q3_pilot_solver.py','pilot_config.json']
    stamp={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
    stamp.update({'../solution/'+n:hashlib.sha256((P/'solution'/n).read_bytes()).hexdigest() for n in ['baseline.py','q1_optimized.py']})
    (out/'source_manifest.json').write_text(json.dumps(stamp,indent=2)+'\n',encoding='utf-8')
    frozen=out/'source_snapshot';frozen.mkdir(exist_ok=True)
    for n in names:(frozen/n).write_bytes((ROOT/n).read_bytes())
    conf=P/'official/data/config.txt';hw=read_evaluation_config(str(conf));sc=read_scene_b_config(str(conf));cache=read_cache_config(str(conf))
    kwargs=dict(bandwidth=hw['bandwidth'],capacity=hw['capacity'],cross_core_copy_delay=sc['cross_core_copy_delay_cycles'])
    def job(case,n):
        d=out/case/f'n{n}';d.mkdir(parents=True,exist_ok=True);begin=time.perf_counter()
        with (d/'console.log').open('w',encoding='utf-8') as f:
            proc=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'q3_pilot_solver.py'),str(P/f'official/data/{case}.json'),'-n',str(n),'--output-dir',str(d)],stdout=f,stderr=subprocess.STDOUT)
        assert proc.returncode==0,(case,n,'solver failed; see console.log')
        run=json.loads((d/'run.json').read_text());plan=json.loads((d/'plan.json').read_text());g=json.loads((P/f'official/data/{case}.json').read_text())
        assert set(plan)=={'node_to_subgraph','core_schedules'}
        assert run['cold_start'] and not run['historical_plans_read'] and run['initial_cache_empty']
        assert run['input_sha256']==hashlib.sha256(json.dumps(g,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with gzip.open(d/'selected_result.json.gz','rt',encoding='utf-8') as f:stored=json.load(f)
        again=evaluate_problem_3(g,plan,**kwargs,**cache)
        assert json.loads(json.dumps(again))==stored,'full official recheck differs'
        without=evaluate_scene_b(g,plan,**kwargs)
        with gzip.open(d/'paired_no_l2.json.gz','wt',encoding='utf-8') as f:json.dump(without,f,separators=(',',':'))
        assert again['data_movement_bytes']==without['data_movement_bytes']
        events=[json.loads(s) for s in (d/'search.jsonl').read_text(encoding='utf-8').splitlines()]
        valid=[e for e in events if e['status']=='ok'];chosen=min(valid,key=lambda e:(e['makespan'],e['added_copy_bytes']))
        return dict(case=case,cores=n,with_l2_cycles=again['makespan'],same_plan_no_l2_cycles=without['makespan'],
            paired_cache_ratio=without['makespan']/again['makespan'],initial_with_l2_cycles=valid[0]['makespan'],
            construction_to_selected_ratio=valid[0]['makespan']/again['makespan'],selected_candidate=chosen['candidate'],
            added_copy_bytes=again['data_movement_bytes']['added_copy_bytes'],hit_rate=again['cache_stats']['hit_rate'],
            hit_bytes=again['cache_stats']['hit_bytes'],miss_bytes=again['cache_stats']['miss_bytes'],
            peak_l1_bytes=max(x['L1'] for x in again['memory_peak_by_core'].values()),
            peak_ub_bytes=max(x['UB'] for x in again['memory_peak_by_core'].values()),
            max_l2_bytes=max((e['used_bytes'] for e in again['cache_events'] if e['event']=='insert'),default=0),
            official_search_calls=run['official_evaluations'],feedback_candidates=run['feedback_proposals_evaluated'],
            invalid_candidates=run['invalid_candidates'],solver_seconds=run['elapsed_seconds'],total_seconds=time.perf_counter()-begin,
            full_result_rechecked=True)
    rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(job,c,n) for c in spec[a.phase] for n in spec['cores']]
        for f in concurrent.futures.as_completed(futures):
            r=f.result();rows.append(r);print(r['case'],r['cores'],r['selected_candidate'],round(r['paired_cache_ratio'],5),flush=True)
            rows.sort(key=lambda r:(r['case'],r['cores']))
            with (out/'metrics.csv').open('w',encoding='utf-8',newline='') as stream:
                w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    for n,h in stamp.items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h,'source changed during pilot'
    summary=dict(phase=a.phase,cases=spec[a.phase],cores=spec['cores'],jobs=len(rows),
        mean_paired_cache_ratio={n:statistics.mean(r['paired_cache_ratio'] for r in rows if r['cores']==n) for n in spec['cores']},
        search_calls=sum(r['official_search_calls'] for r in rows),independent_recheck_calls=len(rows),paired_no_l2_calls=len(rows),
        cold_start=True,all_results_rechecked=True,workers=2,scope='Only this listed small-case sample; not the 100-case official mean.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary))


if __name__=='__main__':main()
