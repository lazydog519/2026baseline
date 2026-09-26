"""Check standalone cold inference against plans frozen before blind evaluation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PKG = HERE / 'standalone_pilot'
OFFICIAL = HERE.parent / 'official' / 'data'
FILES = ('graph_primitives.py', 'mechanism.py', 'stage_candidates.py',
         'fast_fifo.py', 'structural_neighbors.py', 'selection_policy.py',
         'candidate_family.py', 'inference.py', 'model.json')


def plan_sha(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def main():
    frozen = json.loads((HERE / 'blind_holdout_frozen.json').read_text(encoding='utf-8'))
    selected = [r for r in frozen['jobs'] if r['selected']]
    results = []
    with tempfile.TemporaryDirectory(prefix='a_cold_') as tmp:
        root = Path(tmp)
        for name in FILES:
            shutil.copy2(PKG / name, root / name)
        shutil.copy2(OFFICIAL / 'config.txt', root / 'hardware.txt')
        for case in sorted({r['case'] for r in selected}):
            shutil.copy2(OFFICIAL / f'{case}.json', root / f'opaque_{case}.json')
        for r in selected:
            output = root / f"plan_{r['case']}_n{r['cores']}_q{r['question']}.json"
            call = [sys.executable, str(root / 'inference.py'),
                    str(root / f"opaque_{r['case']}.json"), '-n', str(r['cores']),
                    '--question', str(r['question']), '--config', str(root / 'hardware.txt'),
                    '--output', str(output)]
            run = subprocess.run(call, capture_output=True, text=True, timeout=120)
            if run.returncode:
                raise RuntimeError(run.stderr)
            actual = plan_sha(json.loads(output.read_text(encoding='utf-8')))
            results.append({'case': r['case'], 'cores': r['cores'], 'question': r['question'],
                            'matches_pre_evaluation_plan': actual == r['plan_sha256'],
                            'selected': r['name']})
    report = {'isolated': True, 'official_evaluator_present': False,
              'renamed_graphs_and_config': True, 'checks': len(results),
              'matches': sum(r['matches_pre_evaluation_plan'] for r in results),
              'results': results}
    (HERE / 'standalone_verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print({k: report[k] for k in ('isolated', 'checks', 'matches')})
    assert report['matches'] == len(results)


if __name__ == '__main__':
    main()
