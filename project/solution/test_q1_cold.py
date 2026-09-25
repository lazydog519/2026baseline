"""Small executable checks of scene-A-specific rules, before expensive runs."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from q1_cold import Model,solve,fingerprint


def graph(branches=1,chain=False):
    tensors=[{'id':1,'pos':'DDR','size':16},{'id':2,'pos':'UB','size':16}]
    ops=[{'id':100,'op':'COPY_IN','pipe':'PIPE_MTE2','cycles':1}]
    edges=[{'source':1,'target':100},{'source':100,'target':2}]
    for i in range(branches):
        t=3+i*2;o=101+i*2
        tensors.extend([{'id':t,'pos':'UB','size':16},{'id':t+1,'pos':'DDR','size':16}])
        ops.extend([{'id':o,'op':'ADD','pipe':'PIPE_V','cycles':4},{'id':o+1,'op':'COPY_OUT','pipe':'PIPE_MTE3','cycles':1}])
        edges.extend({'source':a,'target':b} for a,b in [(2 if not chain or i==0 else t-2,o),(o,t),(t,o+1),(o+1,t+1)])
    return dict(ops=ops,tensors=tensors,edges=edges)


def main():
    p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'official/code'))
    from multicore_cut_evaluate_problem_1 import evaluate_scene_a
    from evaluation_validation import validate_task_order
    from stub_multicore_cut_and_schedule import derive_multicore_plan
    from baseline import make_plan
    kwargs=dict(bandwidth=60,capacity={'L1':524288,'UB':131072},same_core_wait=100,cross_core_wait=1000)
    manifest=json.loads((p/'official_manifest.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((p/'official'/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in manifest['files'])
    g=graph(2,True);mapping={'101':0,'103':1}
    same={'node_to_subgraph':mapping,'core_schedules':[[0,1],[]]}
    cross={'node_to_subgraph':mapping,'core_schedules':[[0],[1]]}
    a=evaluate_scene_a(g,same,**kwargs);b=evaluate_scene_a(g,cross,**kwargs)
    assert a['makespan']==112 and b['makespan']==1012,(a['makespan'],b['makespan'])
    assert a['data_movement_bytes']==b['data_movement_bytes'],'fixed partition traffic depends on core assignment'
    for count in (1,3):
        gg=graph(count);plan={'node_to_subgraph':{str(101+2*i):i for i in range(count)},'core_schedules':[[i] for i in range(count)]+[[]]}
        model=Model(gg,60,100,1000);v=model.describe(plan);res=evaluate_scene_a(gg,plan,**kwargs)
        assert v['bytes']==res['data_movement_bytes']['scheduled_copy_bytes']-res['data_movement_bytes']['spill_added_copy_bytes']
        validate_task_order(derive_multicore_plan(gg,model.greedy(plan)))
    fan=graph(3)
    fan['ops']=[o for o in fan['ops'] if o['id']!=102]
    fan['tensors']=[t for t in fan['tensors'] if t['id']!=4]
    fan['edges']=[dict(source=3 if e['source']==2 and e['target'] in (103,105) else e['source'],target=e['target'])
                  for e in fan['edges'] if 102 not in (e['source'],e['target'])]
    fanplan={'node_to_subgraph':{'101':0,'103':1,'105':2},'core_schedules':[[0],[1],[2]]}
    fanres=evaluate_scene_a(fan,fanplan,**kwargs)
    assert Model(fan,60,100,1000).describe(fanplan)['bytes']==96
    assert fanres['data_movement_bytes']['partition_added_copy_bytes']==48,'one producer write plus two consumer reads'
    pressure = {
        'tensors': [{'id':i,'pos':'DDR' if i in (1,6) else 'UB','size':50000 if i<5 else 16} for i in range(1,7)],
        'ops': [{'id':100+i,'op':'COPY_IN' if i==0 else 'COPY_OUT' if i==4 else 'ADD',
                 'pipe':'PIPE_MTE2' if i==0 else 'PIPE_MTE3' if i==4 else 'PIPE_V','cycles':4} for i in range(5)],
        'edges':[{'source':a,'target':b} for a,b in
                 [(1,100),(100,2),(2,101),(101,3),(3,102),(102,4),(2,103),(4,103),(103,5),(5,104),(104,6)]]}
    pr=evaluate_scene_a(pressure,make_plan(pressure,2),**kwargs)
    assert pr['data_movement_bytes']['spill_added_copy_bytes']>0
    assert all(x['UB']<=kwargs['capacity']['UB'] for x in pr['memory_peak_by_core'].values())
    # A two-core waiting cycle induced by core orders must be rejected.
    bad={'node_to_subgraph':mapping,'core_schedules':[[1,0],[]]}
    try:validate_task_order(derive_multicore_plan(g,bad))
    except (ValueError,RuntimeError):pass
    else:raise AssertionError('illegal serial order accepted')
    config=json.loads((p/'solution/q1_cold_config.json').read_text());saved={}
    with tempfile.TemporaryDirectory(prefix='q1_independent_') as tmp:
        root=Path(tmp)
        for j,count in enumerate((1,3,3,1)):
            gg=graph(count);before=fingerprint(gg);folder=root/str(j)
            r=solve(gg,2,p/'official/code',p/'official/data/config.txt',config,folder/'plan.json',folder)
            assert fingerprint(gg)==before
            pair=(r['selected_fingerprint'],r['makespan_cycles'])
            assert count not in saved or saved[count]==pair
            saved[count]=pair
            if count==1:assert r['makespan_cycles']==6
        strong=graph(1);strong['ops'][1]['cycles']=10000
        folder=root/'certificate'
        cert=solve(strong,2,p/'official/code',p/'official/data/config.txt',config,folder/'plan.json',folder)
        assert cert['evaluations']==1 and cert['stop_reason']=='certified_gap'
        assert cert['makespan_cycles']<=1.03*cert['global_lower_bound_cycles']
        isolated=root/'isolated';isolated.mkdir()
        for name in ('q1_cold.py','q1_cold_config.json','q1_optimized.py','baseline.py'):
            shutil.copy2(p/'solution'/name,isolated/name)
        shutil.copytree(p/'official/code',isolated/'official',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(p/'official/data/config.txt',isolated/'config.txt')
        (isolated/'renamed.json').write_text(json.dumps(graph(3)))
        subprocess.run([sys.executable,str(isolated/'q1_cold.py'),str(isolated/'renamed.json'),'-n','2',
                        '--official-code',str(isolated/'official'),'-o',str(isolated/'answer.json')],check=True,capture_output=True)
        assert fingerprint(json.loads((isolated/'answer.json').read_text()))==saved[3][0]
    print('PASS: 114 official hashes; appendix=6; same-core wait=100/cross-core=1000; boundary bytes; legal spill/capacity; no same-core DDR exemption; cycle rejection; input unchanged; case-order independence; isolated renamed input.')


if __name__=='__main__':main()
