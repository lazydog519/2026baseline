"""Small deterministic checks for the Q2 locality metric and official plan contract."""
import json,sys,unittest
from pathlib import Path
PKG=Path(__file__).resolve().parents[1];ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(PKG/'solution'));sys.path.insert(0,str(ROOT/'project'/'official'/'code'))
from q2_final_baseline import make_plan
from q2_final_solver import Problem
from evaluation_validation import read_evaluation_config,validate_graph
from multicore_cut_evaluate_problem_2 import evaluate_scene_b,read_scene_b_config
class FinalQ2Smoke(unittest.TestCase):
 def test_locality_profile_and_official_candidate(self):
  graph=json.loads((ROOT/'project/official/data/case_001.json').read_text(encoding='utf-8'))
  config=ROOT/'project/official/data/config.txt';settings=read_evaluation_config(str(config));delay=read_scene_b_config(str(config))['cross_core_copy_delay_cycles']
  validate_graph(graph);plan=make_plan(graph,2)
  problem=Problem(graph,2,settings['bandwidth'],delay,settings['capacity'])
  profile=problem.locality_profile(plan)
  self.assertGreaterEqual(profile['locality_ratio'],0.0);self.assertLessEqual(profile['locality_ratio'],1.0)
  self.assertGreaterEqual(profile['internalized_bytes'],0)
  result=evaluate_scene_b(graph,plan,bandwidth=settings['bandwidth'],capacity=settings['capacity'],cross_core_copy_delay=delay)
  self.assertGreater(result['makespan'],0)
  self.assertIn('spill_added_copy_bytes',result['data_movement_bytes'])
if __name__=='__main__':unittest.main()
