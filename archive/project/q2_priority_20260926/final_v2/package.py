"""Package evaluator-free Scene-B inference and verify renamed-input replay."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, required=True)
    args = ap.parse_args()
    project, root = args.project.resolve(), Path(__file__).resolve().parent
    names = ('solver.py', 'model.py', 'memory_proxy.py', 'q1_optimized.py', 'baseline.py')
    manifest = json.loads((root/'full_generation_manifest.json').read_text(encoding='utf-8'))
    for name in names:
        if sha(root/name) != manifest['source_sha256'][name]:
            raise ValueError(f'frozen package member changed: {name}')
    package = root/'submission_q2.zip'
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(root/name, name)
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        with zipfile.ZipFile(package) as archive:
            archive.extractall(folder)
        for case in ('case_010', 'case_078'):
            graph = folder/f'unseen_name_{case[-3:]}.json'
            graph.write_bytes((project/'official/data'/f'{case}.json').read_bytes())
            output = folder/f'{case}_multicore_res.json'
            subprocess.run([sys.executable, '-X', 'utf8', str(folder/'solver.py'),
                            str(graph), '-n', '5', '--config',
                            str(project/'official/data/config.txt'), '-o', str(output)],
                           check=True, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=180)
            frozen = root/'full_plans'/f'{case}_n5.json'
            if json.loads(output.read_text(encoding='utf-8')) != json.loads(frozen.read_text(encoding='utf-8')):
                raise ValueError(f'isolated replay differs: {case}')
            checks.append(dict(case=case, cores=5, renamed_input=True,
                               plan_matches_frozen=True))
    report = dict(package_sha256=sha(package), members=list(names),
                  official_evaluator_in_package=False,
                  case_specific_results_in_package=False, replays=checks)
    (root/'package_verification.json').write_text(json.dumps(report, indent=2)+'\n',
                                                   encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
