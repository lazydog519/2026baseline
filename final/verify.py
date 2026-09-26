"""Verify immutable sources/data; --smoke replays one renamed graph for all three solvers."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--smoke',action='store_true');a=p.parse_args()
m=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
for group in ['solver_sha256','data_sha256']:
    for name,expected in m[group].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected,name
result={'source_files_unchanged':len(m['solver_sha256']),'data_files_unchanged':len(m['data_sha256']),'smoke':[],'official_evaluator_calls':0}
if a.smoke:
    with tempfile.TemporaryDirectory(prefix='huawei_portable_') as td:
        tmp=Path(td);graph=tmp/'unseen_filename.json';graph.write_bytes((ROOT/'examples/case_001.json').read_bytes())
        for q in ['q1','q2','q3']:
            output=tmp/(q+'.json')
            subprocess.run([sys.executable,str(ROOT/'code'/q/'solver.py'),str(graph),'-n','5','--config',str(ROOT/'code/config.txt'),'-o',str(output)],cwd=tmp,check=True,timeout=120,capture_output=True)
            assert json.loads(output.read_text())==json.loads((ROOT/'examples'/f'{q}_expected_n5.json').read_text()),q
            result['smoke'].append({'solver':q,'renamed_input':True,'matches_frozen_plan':True})
(ROOT/'docs'/('package_verification.json' if a.smoke else 'integrity_check.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
