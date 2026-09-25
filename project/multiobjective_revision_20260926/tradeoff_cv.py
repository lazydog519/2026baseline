"""Cheap policy screen on development labels; never used in submission inference."""
import json
from collections import defaultdict
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'all_questions_fresh_v3'
sys.path.insert(0, str(SOURCE))
from experiment import fit  # current-round calibration routine; no evaluator call


def unit(values):
    values = np.asarray(values, dtype=float)
    gap = values.max() - values.min()
    return (values - values.min()) / gap if gap > 1e-12 else np.zeros_like(values)


def main():
    rows = json.loads((SOURCE / 'training_labels.json').read_text(encoding='utf-8'))
    records = []
    for row in rows:
        if row['status'] != 'ok':
            continue
        detail = json.loads((SOURCE / row['path'] / 'features.json').read_text(encoding='utf-8'))
        cache = detail['detail']['cache_request_proxy'] or {'hit_bytes': 0, 'read_bytes': 0}
        records.append({**row, 'features': detail['features'],
                        'proxy_bytes': detail['detail']['no_hit_copy_bytes'],
                        'proxy_hit_rate': cache['hit_bytes'] / max(1, cache['read_bytes'])})
    policies = ('latency', 'weighted_90', 'weighted_90_guard2', 'weighted_80', 'epsilon_2pct')
    selected = defaultdict(list)
    for q in (1, 2, 3):
        data = [r for r in records if r['question'] == q]
        x = np.asarray([r['features'] for r in data], dtype=float)
        y = np.asarray([r['makespan'] for r in data], dtype=float)
        groups = {(r['case'], r['cores']) for r in data}
        scale = {group: max(1, min(x[i, 0] for i, r in enumerate(data)
                                   if (r['case'], r['cores']) == group)) for group in groups}
        s = np.asarray([scale[r['case'], r['cores']] for r in data])
        for case in sorted({r['case'] for r in data}):
            keep = np.asarray([r['case'] != case for r in data])
            w = fit(x[keep] / s[keep, None], y[keep] / s[keep], .01)
            for n in (2, 5):
                ids = [i for i, r in enumerate(data) if r['case'] == case and r['cores'] == n]
                if not ids:
                    continue
                pred = np.asarray([max(x[i, 0], x[i] @ w) for i in ids])
                b = np.asarray([data[i]['proxy_bytes'] for i in ids], dtype=float)
                h = np.asarray([data[i]['proxy_hit_rate'] for i in ids], dtype=float)
                tn, bn, hn = unit(pred), unit(b), unit(h)
                # Normalization is within one graph/core/scene; no cross-case units mix.
                scores = {
                    'latency': pred,
                    'weighted_90': .90 * tn + (.08 if q == 3 else .10) * bn + (.02 * (1 - hn) if q == 3 else 0),
                    'weighted_80': .80 * tn + (.15 if q == 3 else .20) * bn + (.05 * (1 - hn) if q == 3 else 0),
                }
                scores['weighted_90_guard2'] = np.where(pred <= 1.02 * pred.min(),
                                                         scores['weighted_90'], float('inf'))
                near = np.flatnonzero(pred <= 1.02 * pred.min())
                chosen = {p: int(np.argmin(v)) for p, v in scores.items()}
                chosen['epsilon_2pct'] = min(near, key=lambda j: (b[j], -h[j], pred[j]))
                oracle = min(y[ids])
                for policy in policies:
                    row = data[ids[chosen[policy]]]
                    selected[q, policy].append(dict(case=case, cores=n, name=row['name'],
                        makespan=row['makespan'], regret=row['makespan']/oracle-1,
                        added_bytes=row['data_movement_bytes']['added_copy_bytes'],
                        predicted_cycles=float(pred[chosen[policy]])))
    report = {'scope': '9 development graphs, 2/5 cores, leave-one-graph-out; policy screen only',
              'official_calls': 0, 'policies': {}, 'selected': {}}
    for q in (1, 2, 3):
        base = selected[q, 'latency']
        base_by_key = {(r['case'], r['cores']): r for r in base}
        report['policies'][str(q)] = {}
        for policy in policies:
            values = selected[q, policy]
            ratios = [r['added_bytes'] / base_by_key[r['case'], r['cores']]['added_bytes']
                      if base_by_key[r['case'], r['cores']]['added_bytes'] else
                      (1.0 if r['added_bytes'] == 0 else float('inf')) for r in values]
            report['policies'][str(q)][policy] = dict(groups=len(values),
                mean_oracle_regret=float(np.mean([r['regret'] for r in values])),
                mean_added_bytes_ratio_vs_latency=float(np.mean(ratios)),
                time_improvements_vs_latency=sum(r['makespan'] < base_by_key[r['case'], r['cores']]['makespan'] for r in values),
                time_regressions_vs_latency=sum(r['makespan'] > base_by_key[r['case'], r['cores']]['makespan'] for r in values))
            report['selected'][f'q{q}_{policy}'] = values
    (ROOT / 'tradeoff_cv.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for q, policies in report['policies'].items():
        print('Q'+q, [(p, round(v['mean_oracle_regret'],4), round(v['mean_added_bytes_ratio_vs_latency'],3),
                      v['time_improvements_vs_latency'], v['time_regressions_vs_latency']) for p,v in policies.items()])


if __name__ == '__main__':
    main()
