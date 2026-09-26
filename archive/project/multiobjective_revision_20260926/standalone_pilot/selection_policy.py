"""Pure graph-candidate selector: no official evaluator, labels or old plans."""
import numpy as np


def design_proxy(group):
    base = group[0]
    f0 = np.asarray(base['proxy']['features'], dtype=float)
    b0 = base['proxy']['copy_bytes_proxy']
    h0 = base['proxy']['l2_hit_proxy']
    rows = []
    for r in group[1:]:
        f = np.asarray(r['proxy']['features'], dtype=float)
        typ = r['name'].split('_s')[0]
        rows.append([*((f-f0)/max(1., f0[0])),
                     (r['proxy']['copy_bytes_proxy']-b0)/max(1., b0),
                     (r['proxy']['l2_hit_proxy']-h0)/max(1., b0),
                     *[int(typ == name) for name in ('migrate', 'split', 'swap')],
                     int(r['cores'] == 5)])
    return np.asarray(rows)


def choose(group, coefficients, margin):
    x = design_proxy(group)
    scores = np.r_[0., x @ np.asarray(coefficients, dtype=float)]
    scores[1:] += .02 * np.maximum(0, x[:, 5])
    scores[1:] += margin
    scores[1:][x[:, 3] > 1e-12] = np.inf
    return int(np.argmin(scores)), scores.tolist()
