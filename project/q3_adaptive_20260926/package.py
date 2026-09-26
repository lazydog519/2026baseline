"""Export pure inference only and replay renamed inputs in an isolated folder."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
from solver import SOURCES

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    manifest=json.loads((ROOT/'full5_v2/generation_manifest.json').read_text(encoding='utf-8'))
    for s,h in manifest['source_sha256'].items():
        if sha(ROOT/s)!=h:raise ValueError('frozen source modified')
    target=ROOT/'submission_q3.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name in SOURCES:z.write(ROOT/name,name)
    records=[]
    with tempfile.TemporaryDirectory(prefix='q3_isolated_') as tmp:
        folder=Path(tmp)
        with zipfile.ZipFile(target) as z:z.extractall(folder)
        shutil.copy2(PROJECT/'official/data/config.txt',folder/'fixed.cfg')
        for case in ('case_011','case_078'):
            shutil.copy2(PROJECT/'official/data'/f'{case}.json',folder/'unknown_graph.json')
            subprocess.run([sys.executable,'-I','-X','utf8','-c',
                "import runpy,sys;sys.path.insert(0,'.');sys.argv=['solver.py','unknown_graph.json','-n','5','--config','fixed.cfg','-o','answer.json'];runpy.run_path('solver.py',run_name='__main__')"],
                cwd=folder,capture_output=True,text=True,encoding='utf-8',check=True)
            match=json.loads((folder/'answer.json').read_text())==json.loads(
                (ROOT/'full5_v2/plans'/f'{case}_n5.json').read_text())
            if not match:raise ValueError('renamed input result mismatch')
            records.append(dict(case=case,renamed_input=True,plan_matches_frozen=True))
    report=dict(package_sha256=sha(target),members=list(SOURCES),
                official_evaluator_in_package=False,case_specific_results_in_package=False,
                replays=records,source_sha256=manifest['source_sha256'])
    (ROOT/'package_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
