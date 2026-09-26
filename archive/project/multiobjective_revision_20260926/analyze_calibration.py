"""Leave-one-graph-out and untouched-holdout selection audit; no evaluator."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
from selection_policy import choose, design_proxy

HERE = Path(__file__).resolve().parent
frozen = json.loads((HERE / 'neighbor_candidates_frozen.json').read_text(encoding='utf-8'))
rows = [json.loads(line) for line in
        (HERE / 'neighbor_calibration_labels.jsonl').read_text(encoding='utf-8').splitlines()]
assert len(rows) == len(frozen['jobs']) == 192
assert all(r['official']['status'] == 'ok' for r in rows)
groups = defaultdict(list)
for r in rows:
    groups[(r['case'], r['cores'], r['question'])].append(r)
assert len(groups) == 48 and all(len(v) == 4 for v in groups.values())


def design(group):
    base = group[0]
    x = design_proxy(group)
    y = [r['official']['makespan']/base['official']['makespan']-1 for r in group[1:]]
    return x, np.asarray(y)


def fit(keys, lam):
    x = np.concatenate([design(groups[k])[0] for k in keys])
    y = np.concatenate([design(groups[k])[1] for k in keys])
    scale = np.sqrt(np.mean(x*x, axis=0))
    scale[scale < 1e-10] = 1
    z = x / scale
    coef = np.linalg.solve(z.T@z + lam*np.eye(z.shape[1]), z.T@y) / scale
    return coef


def audit(keys, source_keys, lam, margin, leave_one_case):
    outputs = []
    for key in keys:
        train = [k for k in source_keys if k[2] == key[2] and
                 (not leave_one_case or k[0] != key[0])]
        coef = fit(train, lam)
        group = groups[key]
        chosen, p = choose(group, coef, margin)
        base_t = group[0]['official']['makespan']
        actual = group[chosen]['official']['makespan']
        outputs.append({'case': key[0], 'cores': key[1], 'question': key[2],
                        'selected': group[chosen]['name'], 'predicted_delta': float(p[chosen]),
                        'seed_cycles': base_t, 'selected_cycles': actual,
                        'relative_time_change': actual/base_t-1,
                        'oracle_cycles': min(r['official']['makespan'] for r in group)})
    return outputs


def summarize(results):
    delta = np.asarray([r['relative_time_change'] for r in results])
    return {'groups': len(results), 'selected_changes': sum(r['selected'] != groups[r['case'],r['cores'],r['question']][0]['name'] for r in results),
            'improved': int((delta < -1e-12).sum()), 'regressed': int((delta > 1e-12).sum()),
            'mean_time_change': float(delta.mean()), 'worst_time_change': float(delta.max())}


def main():
    train = sorted(k for k in groups if k[0] in frozen['train'])
    hold = sorted(k for k in groups if k[0] in frozen['holdout'])
    grid = []
    for lam in (0.3, 1., 3., 10.):
        for margin in (0., .01, .02, .03, .05):
            loo = audit(train, train, lam, margin, True)
            grid.append({'ridge_lambda': lam, 'margin': margin, **summarize(loo)})
    # Primary criterion: no LOCO time regressions; next largest time reduction,
    # next smallest number of selected changes. This rule is fixed before holdout.
    safe = [r for r in grid if r['regressed'] == 0]
    chosen = min(safe or grid, key=lambda r: (r['regressed'], r['mean_time_change'], r['selected_changes'], r['ridge_lambda'], r['margin']))
    held = audit(hold, train, chosen['ridge_lambda'], chosen['margin'], False)
    report = {'scope': 'new bounded-move labels; 6 graph LOCO + 2 preselected holdout graphs',
              'policy': 'per-question relative ridge, 2% positive DDR penalty, prediction margin; reject added logical L1/UB excess',
              'selection_rule': 'zero LOCO regressions, then mean time improvement; first preselected holdout was seen during the diagnostic revision and is not blind evidence',
              'train_grid': grid, 'selected_policy': chosen,
              'holdout': summarize(held), 'holdout_rows': held,
              'train_groups': len(train), 'holdout_groups': len(hold),
              'official_label_jobs': len(rows)}
    (HERE / 'neighbor_calibration_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    policy = {'scope': 'fresh six-graph calibration only; no official call in inference',
              'ridge_lambda': chosen['ridge_lambda'], 'margin': chosen['margin'],
              'positive_ddr_penalty': .02, 'reject_increased_logical_memory_excess': True,
              'coefficients': {str(q): fit([k for k in train if k[2] == q], chosen['ridge_lambda']).tolist()
                               for q in (1, 2, 3)},
              'train_cases': frozen['train'],
              'train_labels_sha256': hashlib.sha256(json.dumps(
                  [r for r in rows if r['case'] in frozen['train']],
                  sort_keys=True).encode()).hexdigest(),
              'selector_sha256': hashlib.sha256((HERE / 'selection_policy.py').read_bytes()).hexdigest()}
    model_path = HERE / 'neighbor_policy_frozen.json'
    if model_path.exists():
        assert json.loads(model_path.read_text(encoding='utf-8')) == policy
    else:
        model_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding='utf-8')
    print('selected', chosen)
    print('holdout', report['holdout'])
    for r in held:
        print(r['case'],r['cores'],r['question'],r['selected'],round(r['relative_time_change'],4))


if __name__ == '__main__':
    main()
