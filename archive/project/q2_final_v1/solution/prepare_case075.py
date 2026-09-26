"""Recreate the Q2 case-075 initial and selected official Scene-B traces."""
import gzip, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PKG=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PKG/'solution'))
sys.path.insert(0,str(ROOT/'project'/'official'/'code'))
from q2_final_baseline import make_plan
from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config
from evaluation_validation import read_evaluation_config
p=ROOT/'project'/'official'
g=json.loads((p/'data'/'case_075.json').read_text(encoding='utf-8'))
cfg=p/'data'/'config.txt'
settings=read_evaluation_config(str(cfg))
delay=read_scene_b_config(str(cfg))['cross_core_copy_delay_cycles']
initial=evaluate_scene_b(g,make_plan(g,5),bandwidth=settings['bandwidth'],capacity=settings['capacity'],cross_core_copy_delay=delay)
d=PKG/'results'/'runs'/'case_075'/'n5'
plan=json.loads((d/'case_075_plan.json').read_text(encoding='utf-8'))
selected=evaluate_scene_b(g,plan,bandwidth=settings['bandwidth'],capacity=settings['capacity'],cross_core_copy_delay=delay)
run=json.loads((d/'run.json').read_text(encoding='utf-8'))
assert selected['makespan']==run['makespan_cycles'], (selected['makespan'],run['makespan_cycles'])
out=PKG/'results'/'examples';out.mkdir(parents=True,exist_ok=True)
for name,obj in [('case_075_n5_initial.json.gz',initial),('case_075_n5_selected.json.gz',selected)]:
 with gzip.open(out/name,'wt',encoding='utf-8',compresslevel=2) as f:json.dump(obj,f,separators=(',',':'))
print(json.dumps({'initial_cycles':initial['makespan'],'selected_cycles':selected['makespan'],'matches_run':True,'active_core_ops':{str(c['core_id']):len(c['ops']) for c in selected['per_core_timeline']}},indent=2))
