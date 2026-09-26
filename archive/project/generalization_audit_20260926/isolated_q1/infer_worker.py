"""Run frozen inference in an isolated folder; official imports are forbidden."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
reads = set()


def trace(event, args):
    if event == 'import' and any(s in args[0] for s in ('evaluation', 'schedule_step', 'multicore_cut')):
        raise RuntimeError('official module import forbidden: '+args[0])
    if event == 'open' and isinstance(args[0], str):
        path = Path(args[0]).resolve()
        reads.add(str(path))
        if 'A题三问求解' in str(path) and not path.is_relative_to(ROOT):
            raise RuntimeError('external project access forbidden: '+str(path))


sys.addaudithook(trace)
import solver
from baseline import make_plan


def solve(graph, n, question):
    if question == 1:
        rows, rejected = solver.candidates(graph, n, *solver.hardware(ROOT/'config.txt'))
        best = solver.choose(rows, json.loads((ROOT/'policy.json').read_text()))
        return best['plan'], {'selected': best['name'], 'candidates': len(rows),
                              'rejected': rejected, 'proxy': best['proxy_cycles']}
    plan, report = solver.solve(graph, n, ROOT/'config.txt')
    selected = next(r for r in report['candidates'] if r['family'] == report['selected'])
    return plan, {'selected': report['selected'], 'candidates': len(report['candidates']),
                  'rejected': report['rejected'], 'proxy': selected['proxy_cycles']}


def main():
    question = int(sys.argv[1])
    jobs = json.loads((ROOT/'jobs.json').read_text())
    results = []
    for job in jobs:
        graph = json.loads((ROOT/'inputs'/job['file']).read_text())
        before = json.dumps(graph, sort_keys=True)
        row = dict(job)
        start = time.perf_counter()
        try:
            plan, report = solve(graph, job['cores'], question)
            row.update(status='generated', plan=plan, report=report,
                       component=make_plan(graph, job['cores']))
        except Exception as exc:
            row.update(status='rejected', error=repr(exc))
        row.update(seconds=time.perf_counter()-start,
                   input_unchanged=(before == json.dumps(graph, sort_keys=True)))
        results.append(row)
    # Mutate outputs independently to test the local validation boundary.
    graph = json.loads((ROOT/'inputs'/'serial.json').read_text())
    base = make_plan(graph, 2)
    ids = sorted(int(x) for x in base['node_to_subgraph'])
    bad = {}
    for name, value in [('negative_subgraph', -1), ('boolean_subgraph', True)]:
        bad[name] = {'node_to_subgraph': {str(i): value for i in ids},
                     'core_schedules': [[value], []]}
    bad['missing_op'] = copy.deepcopy(base)
    bad['missing_op']['node_to_subgraph'].pop(str(ids[0]))
    bad['order_cycle'] = {'node_to_subgraph': {str(i): int(j >= len(ids)//2) for j,i in enumerate(ids)},
                          'core_schedules': [[1, 0], []]}
    checks = []
    for name, plan in bad.items():
        try:
            if question == 1:
                model = solver.Model(graph, *solver.hardware(ROOT/'config.txt'))
                solver.validate(model, plan, 2)
            else:
                problem = solver.Problem(graph, 2, *solver.hardware(ROOT/'config.txt'))
                solver.validate(problem, plan)
            checks.append(dict(name=name, rejected=False))
        except Exception as exc:
            checks.append(dict(name=name, rejected=True, error=repr(exc)))
    (ROOT/'inference.json').write_text(json.dumps(dict(jobs=results, validator_checks=checks,
        read_paths=sorted(reads), official_modules=[m for m in sys.modules if
            any(s in m for s in ('evaluation_validation', 'multicore_cut', 'schedule_step'))]),
        ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
