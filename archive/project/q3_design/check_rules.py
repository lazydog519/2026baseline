"""Tiny rule probes only; these synthetic graphs are not contest scores."""
import hashlib
import json
import sys
from pathlib import Path

P=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(P/'official/code'))
from evaluation_validation import read_evaluation_config
from multicore_cut_evaluate_problem_3 import evaluate_problem_3,read_cache_config,read_scene_b_config
from multicore_cut_evaluate_problem_2 import evaluate_scene_b


def graph():
    tensors=[dict(id=1,pos='DDR',size=600),dict(id=2,pos='UB',size=600)]
    ops=[dict(id=100,op='COPY_IN',pipe='PIPE_MTE2',cycles=1)]
    edges=[dict(source=1,target=100),dict(source=100,target=2)]
    for op,x in [(101,3),(103,5)]:
        tensors += [dict(id=x,pos='UB',size=16),dict(id=x+1,pos='DDR',size=16)]
        ops += [dict(id=op,op='ADD',pipe='PIPE_V',cycles=4),dict(id=op+1,op='COPY_OUT',pipe='PIPE_MTE3',cycles=1)]
        edges += [dict(source=a,target=b) for a,b in [(2,op),(op,x),(x,op+1),(op+1,x+1)]]
    return dict(tensors=tensors,ops=ops,edges=edges)


def main():
    path=P/'official/data/config.txt'
    cfg=read_evaluation_config(str(path));sc=read_scene_b_config(str(path));cache=read_cache_config(str(path))
    kwargs=dict(bandwidth=cfg['bandwidth'],capacity=cfg['capacity'],cross_core_copy_delay=sc['cross_core_copy_delay_cycles'])
    manifest=json.loads((P/'official_manifest.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((P/'official'/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in manifest['files'])
    g=graph();plan=dict(node_to_subgraph={'101':0,'103':1},core_schedules=[[0],[1]])
    same_time=evaluate_problem_3(g,plan,**kwargs,**cache)
    assert same_time['cache_stats']['copy_in_misses']==2 and same_time['cache_stats']['copy_in_hits']==0
    assert evaluate_problem_3(g,plan,**kwargs,**cache)==same_time,'Cache state persisted across calls'
    # Add a legal independent branch to the synthetic input, then compare TWO
    # plans of this SAME graph. No op is injected into an official input graph.
    g['tensors'] += [dict(id=i,pos='DDR' if i in (80,83) else 'UB',size=6000 if i<82 else 16) for i in range(80,84)]
    g['ops'] += [dict(id=200,op='COPY_IN',pipe='PIPE_MTE2',cycles=1),
                 dict(id=201,op='ADD',pipe='PIPE_V',cycles=4),dict(id=202,op='COPY_OUT',pipe='PIPE_MTE3',cycles=1)]
    g['edges'] += [dict(source=a,target=b) for a,b in [(80,200),(200,81),(81,201),(201,82),(82,202),(202,83)]]
    plans={name:dict(node_to_subgraph={'101':0,'103':1,'201':2},core_schedules=[[0],order])
           for name,order in [('shared_first',[1,2]),('other_input_first',[2,1])]}
    results={name:evaluate_problem_3(g,plan,**kwargs,**cache) for name,plan in plans.items()}
    assert results['other_input_first']['cache_stats']['copy_in_hits']>0
    paired=evaluate_scene_b(g,plans['other_input_first'],**kwargs)
    assert paired['data_movement_bytes']==results['other_input_first']['data_movement_bytes']
    out=dict(scope='Synthetic rule probes, not official case results; all hardware parameters unchanged.',
             same_time_misses=same_time['cache_stats'],fresh_cache_on_repeated_calls=True,
             no_l2_cycles_same_staggered_plan=paired['makespan'],
             official_copy_field_does_not_subtract_cache_hits=True,
             same_graph_plans={name:dict(makespan=r['makespan'],cache=r['cache_stats'],events=r['cache_events']) for name,r in results.items()})
    (Path(__file__).with_name('rule_probe_results.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in out.items() if k!='same_graph_plans'},ensure_ascii=False))
    for name,r in results.items():print(name,r['makespan'],r['cache_stats'])


if __name__=='__main__':main()
