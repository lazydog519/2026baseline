"""Code-only package and renamed-input reproduction in an isolated directory."""
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
P=ROOT.parent


def result(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)


def main():
    archive=ROOT/'q3_nsga_code.zip'
    sources=[ROOT/'solve.py',ROOT/'experiment.json',ROOT/'requirements.txt',
             P/'q3_design/q3_pilot_solver.py',P/'solution/baseline.py',P/'solution/q1_optimized.py',
             P/'official/data/config.txt',*(P/'official/code').glob('*.py')]
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sources:z.write(f,f.relative_to(P).as_posix())
        z.writestr('README.txt','Exploratory Q3 prototype; not a completed full-data submission.\n'
            'Install: python -m pip install -r q3_nsga/requirements.txt\n'
            'Run: python q3_nsga/solve.py /path/to/input.json -n 5 --config official/data/config.txt --method unsga3_npu --seed 17 --output new_run\n'
            'Plan new_run/plan.json contains exactly the two required fields.\n'
            'Only code and fixed configuration included; no input cases or old solutions.\n')
    with tempfile.TemporaryDirectory(prefix='q3_nsga_isolated_') as temp:
        isolated=Path(temp)
        with zipfile.ZipFile(archive) as z:
            assert not any('case_' in x or '/experiment/' in x for x in z.namelist())
            z.extractall(isolated)
        shutil.copyfile(P/'official/data/case_044.json',isolated/'renamed_graph.json')
        completed=subprocess.run([sys.executable,'-X','utf8',str(isolated/'q3_nsga/solve.py'),
            str(isolated/'renamed_graph.json'),'-n','5','--config',str(isolated/'official/data/config.txt'),
            '--method','unsga3_npu','--seed','17','--output',str(isolated/'new_run')],
            cwd=isolated,capture_output=True,text=True,encoding='utf-8')
        assert completed.returncode==0,completed.stderr
        expected=ROOT/'experiment/case_044/n5/unsga3_npu/seed_17'
        assert json.loads((isolated/'new_run/plan.json').read_text())==json.loads((expected/'plan.json').read_text())
        assert result(isolated/'new_run/result.json.gz')==result(expected/'result.json.gz')
        a=json.loads((isolated/'new_run/run.json').read_text());b=json.loads((expected/'run.json').read_text())
        assert a['initial_population_hashes']==b['initial_population_hashes']
        assert a['input_sha256']==b['input_sha256']
    report=dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        code_only=True,renamed_input=True,fresh_process=True,historical_results_absent=True,
        plan_equal=True,full_official_result_equal=True,initial_population_equal=True,
        case='case_044',cores=5,seed=17,method='unsga3_npu',makespan=b['makespan'],
        additional_reproduction_calls=b['official_calls'])
    (ROOT/'isolated_reproduction.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
