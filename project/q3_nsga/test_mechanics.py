"""Small checks before the multi-case experiment; no official files modified."""
import copy
import json
import tempfile
from pathlib import Path
import numpy as np
from pymoo.core.population import Population
from pymoo.core.problem import Problem
from pymoo.algorithms.moo.nsga3 import ReferenceDirectionSurvival
from pymoo.util.ref_dirs import get_reference_directions
from solve import P,ROOT,Model,canonical,run,fp
from check_rules import graph
from stub_multicore_cut_and_schedule import derive_multicore_plan


def main():
    cfg=json.loads((ROOT/'experiment.json').read_text());cfg.update(official_budget=6,population=3,offspring_batch=2,max_proposals_per_budget=8)
    g=graph();original=copy.deepcopy(g);plans=[]
    with tempfile.TemporaryDirectory(prefix='q3_nsga_test_') as temp:
        for i,n in enumerate([2,1,2]):
            out=Path(temp)/str(i)
            result=run(g,n,P/'official/data/config.txt',cfg,'unsga3_npu',17,out)
            plan=json.loads((out/'plan.json').read_text())
            plans.append(plan)
            assert result['cold_start'] and result['empty_l2_each_evaluation']
            assert result['official_calls']<=6
        assert plans[0]==plans[2] and g==original
    # No fictitious objectives, no NaNs when added traffic/miss traffic are constant.
    ref=get_reference_directions('das-dennis',3,n_partitions=2)
    pop=Population.new(F=np.array([[1,0,10],[2,0,10],[3,0,10]],float))
    survived=ReferenceDirectionSurvival(ref).do(Problem(n_var=1,n_obj=3),pop,n_survive=2,random_state=np.random.default_rng(17))
    assert len(survived)==2 and min(survived.get('F')[:,0])==1
    assert np.isfinite(survived.get('dist_to_niche')).all()
    model=Model(g,2,cfg);parent=plans[0];groups,cores=model.parts(parent)
    repaired,order=model.repair(groups,cores,{s:float(-s) for s in groups})
    derive_multicore_plan(g,repaired)
    assert set(parent['node_to_subgraph'])==set(repaired['node_to_subgraph'])
    remap={s:s+100 for s in groups}
    renamed=dict(node_to_subgraph={v:remap[s] for v,s in parent['node_to_subgraph'].items()},
                 core_schedules=[[remap[s] for s in seq] for seq in parent['core_schedules']])
    assert canonical(parent)==canonical(renamed)
    report=dict(synthetic_graph_only=True,cold_core_configuration_order_independent=True,input_unmodified=True,
        constant_objective_normalization_finite=True,dominance_preserved=True,
        canonical_subgraph_ids=True,structural_repair_coverage=True,all_passed=True)
    (ROOT/'unit_checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
