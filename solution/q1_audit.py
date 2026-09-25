"""Re-evaluate each selected Q1 plan with the immutable official evaluator."""
import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import json
import statistics
import sys
from pathlib import Path


def check_job(task):
    p,root,case,n=task
    sys.path.insert(0,str(p/'official/code'))
    from multicore_cut_evaluate_problem_1 import evaluate_scene_a,read_scene_a_config
    from evaluation_validation import read_evaluation_config
    cfg=read_evaluation_config(str(p/'official/data/config.txt'));sc=read_scene_a_config(str(p/'official/data/config.txt'))
    d=root/case/f'n{n}';read=lambda f:json.loads(f.read_text(encoding='utf-8'))
    process=read(d/'process.json');assert process['returncode']==0
    r=read(d/'run.json');g=read(p/f'official/data/{case}.json');plan=read(d/f'{case}_multicore_res.json')
    assert r['cold_start'] and not r['history_read']
    assert set(plan)=={'node_to_subgraph','core_schedules'}
    assert hashlib.sha256(json.dumps(g,sort_keys=True).encode()).hexdigest()==r['graph_sha256']
    assert hashlib.sha256((p/'official/data/config.txt').read_bytes()).hexdigest()==r['config_sha256']
    assert hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()==r['selected_fingerprint']
    assert r['search_config']==read(p/'solution/q1_cold_config.json')
    with gzip.open(d/'official_result.json.gz','rt',encoding='utf-8') as f:stored=json.load(f)
    actual=evaluate_scene_a(g,plan,bandwidth=cfg['bandwidth'],capacity=cfg['capacity'],same_core_wait=sc['task_same_core_wait_cycles'],cross_core_wait=sc['task_cross_core_wait_cycles'])
    for field in ('makespan','data_movement_bytes','memory_peak_by_core'):
        assert json.loads(json.dumps(actual[field]))==stored[field],(case,n,field)
    assert actual['makespan']==r['makespan_cycles']
    assert actual['data_movement_bytes']['added_copy_bytes']==r['added_copy_bytes']
    assert all(x[k]<=cfg['capacity'][k] for x in actual['memory_peak_by_core'].values() for k in ('L1','UB'))
    events=[json.loads(s) for s in (d/'search.jsonl').read_text(encoding='utf-8').splitlines()]
    ok=[e for e in events if e['status']=='ok']
    assert min((e['makespan_cycles'],e['added_copy_bytes']) for e in ok)==(r['makespan_cycles'],r['added_copy_bytes'])
    assert r['evaluations']<=r['search_config']['max_evaluations']
    assert all(e['lower_bound_cycles']<=e['makespan_cycles']+1e-6 for e in ok)
    m=actual['data_movement_bytes']
    return dict(case=case,cores=n,makespan_cycles=r['makespan_cycles'],added_copy_bytes=m['added_copy_bytes'],
                scheduled_copy_bytes=m['scheduled_copy_bytes'],spill_bytes=m['spill_added_copy_bytes'],
                peak_l1_bytes=max(x['L1'] for x in actual['memory_peak_by_core'].values()),
                peak_ub_bytes=max(x['UB'] for x in actual['memory_peak_by_core'].values()),
                evaluations=r['evaluations'],wall_seconds=process['process_wall_s'],selected=r['selected'],
                bound_pruned=r['bound_pruned'],invalid_candidates=r['invalid_candidates'],
                stop_reason=r['stop_reason'],global_lower_bound_cycles=r.get('global_lower_bound_cycles'),
                certified_gap=r.get('certificate_gap'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',type=Path,required=True);ap.add_argument('--runs',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--workers',type=int,default=4)
    a=ap.parse_args();p=a.project.resolve();root=a.runs.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    read=lambda f:json.loads(f.read_text(encoding='utf-8'))
    manifest=read(p/'official_manifest.json')
    for item in manifest['files']:assert hashlib.sha256((p/'official'/item['path']).read_bytes()).hexdigest()==item['sha256']
    frozen=read(p/'q1_cold/frozen_manifest.json')
    for name,digest in frozen['files'].items():assert hashlib.sha256((p/'solution'/name).read_bytes()).hexdigest()==digest
    exp=read(root/'experiment.json');jobs=[(p,root,c,n) for c in exp['cases'] for n in exp['cores']]
    ref={(r['case'],int(r['cores'])):r for r in csv.DictReader((p/'final_metrics/per_case_metrics.csv').open(encoding='utf-8'))}
    rows=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        pending=[pool.submit(check_job,t) for t in jobs]
        for f in concurrent.futures.as_completed(pending):
            r=f.result();base=ref[r['case'],r['cores']]
            r.update(singlecore_cycles=int(float(base['singlecore_cycles'])),baseline_cycles=int(float(base['q1_cycles'])))
            r['speedup']=r['singlecore_cycles']/r['makespan_cycles'];r['baseline_speedup']=r['singlecore_cycles']/r['baseline_cycles']
            r['reduction_percent']=100*(1-r['makespan_cycles']/r['baseline_cycles']);rows.append(r)
            with (out/'audit_progress.csv').open('w',encoding='utf-8',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            print('checked',r['case'],r['cores'],flush=True)
    rows.sort(key=lambda r:(r['case'],r['cores']))
    with (out/'per_case_metrics.csv').open('w',encoding='utf-8',newline='') as s:
        w=csv.DictWriter(s,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    groups={n:[r for r in rows if r['cores']==n] for n in exp['cores']}
    aggregate=dict(schema='q1-independent-audit-v1',complete_cases=len(exp['cases']),missing_jobs=len(jobs)-len(rows),
        evaluated_selections=len(rows),official_recheck=True,rechecked_jobs=len(rows),official_files_unchanged=len(manifest['files']),cold_start=True,
        arithmetic_mean_speedup={1:1.,**{n:statistics.mean(r['speedup'] for r in rs) for n,rs in groups.items()}},
        baseline_mean_speedup={1:1.,**{n:statistics.mean(r['baseline_speedup'] for r in rs) for n,rs in groups.items()}},
        improved_cases={n:sum(r['makespan_cycles']<r['baseline_cycles'] for r in rs) for n,rs in groups.items()},
        regressed_cases={n:sum(r['makespan_cycles']>r['baseline_cycles'] for r in rs) for n,rs in groups.items()},
        median_wall_seconds={n:statistics.median(r['wall_seconds'] for r in rs) for n,rs in groups.items()},
        max_wall_seconds=max(r['wall_seconds'] for r in rows),total_official_search_evaluations=sum(r['evaluations'] for r in rows),
        total_pruned_candidates=sum(r['bound_pruned'] for r in rows),infeasible_candidates=sum(r['invalid_candidates'] for r in rows),
        certificate_stops=sum(r['stop_reason']=='certified_gap' for r in rows),search_config=exp['search_config'])
    (out/'aggregate.json').write_text(json.dumps(aggregate,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(aggregate),flush=True)


if __name__=='__main__':main()
