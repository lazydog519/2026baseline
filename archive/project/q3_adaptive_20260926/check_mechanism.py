"""Small independent mechanism examples before official development cases."""
import ast
import json
from pathlib import Path
from engine import simulate
from solver import hardware,solve,SOURCES


def check():
    read=lambda c,size,key:(c,'PIPE_MTE2',size,key,True)
    # Simultaneous cold reads cannot hit before the first transfer completes.
    x=simulate([read(0,600,1),read(1,600,1)],[{},{}],1200,60,250)
    assert abs(x['event_cycles']-20)<1e-8 and x['hit_bytes']==0
    # A read issued after insertion uses the independent L2 pool.
    x=simulate([read(0,600,1),read(1,600,1)],[{},{0:0}],1200,60,250)
    assert abs(x['event_cycles']-12.4)<1e-8 and x['hit_bytes']==600
    # FIFO hit does not refresh: A, B, A(hit), C evicts A, A misses.
    x=simulate([read(0,600,k) for k in (1,2,1,3,1)],
               [{},{0:0},{1:0},{2:0},{3:0}],1200,60,250)
    assert x['hit_bytes']==600 and x['evictions']==2
    x=simulate([read(0,600,1),read(1,600,1)],[{},{0:0}],500,60,250)
    assert x['hit_bytes']==0 and abs(x['event_cycles']-20)<1e-8
    # Cache and DDR do not divide one combined bandwidth pool.
    x=simulate([read(0,600,1),read(1,600,1),read(2,600,2)],
               [{},{0:0},{0:0}],1200,60,250)
    assert abs(x['event_cycles']-20)<1e-8 and x['hit_bytes']==600
    # A hit evicted while in flight is inserted again at completion.
    x=simulate([read(0,600,1),read(1,600,1),read(2,600,2),
                read(2,600,3),read(3,600,1)],
               [{},{0:0},{0:0},{2:0},{1:0}],1200,60,1)
    assert x['hit_bytes']==1200 and x['evictions']==2
    here=Path(__file__).resolve().parent
    cfg=hardware(here.parent/'official/data/config.txt')
    policy=json.loads((here/'policy.json').read_text())
    checked=0
    for count,links in ((1,[]),(5,[]),(5,[(0,1),(1,2),(2,3),(3,4)]),
                        (4,[(0,1),(0,2),(1,3),(2,3)])):
        graph={'ops':[{'id':i,'op':'ADD','pipe':'PIPE_V','cycles':50} for i in range(count)],
               'tensors':[{'id':100+i,'pos':'UB','size':32} for i in range(count)],
               'edges':[{'source':i,'target':100+i} for i in range(count)]+
                       [{'source':100+a,'target':b} for a,b in links]}
        for n in (1,2,5):
            plan,report=solve(graph,n,cfg,policy)
            assert report['official_evaluator_calls']==0
            assert set(plan)=={'node_to_subgraph','core_schedules'}
            checked+=1
    for name in SOURCES:
        if not name.endswith('.py'): continue
        tree=ast.parse((here/name).read_text(encoding='utf-8'))
        imports=[x.module for x in ast.walk(tree) if isinstance(x,ast.ImportFrom)]
        assert not any(x and x.startswith(('multicore_cut_evaluate','schedule_step',
                                          'evaluation_validation')) for x in imports)
    result=dict(mechanism_checks=6,synthetic_graph_core_runs=checked,passed=True)
    (here/'mechanism_checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result)


if __name__=='__main__': check()
