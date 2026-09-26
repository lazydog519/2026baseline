"""Input-derived stage seeds and bounded legal moves; evaluator-free."""
from graph_primitives import Graph
from stage_candidates import stage_plan
from structural_neighbors import candidates as neighbors


def proxy(g, plan, cfg, q):
    features, detail = g.features(plan, cfg, q)
    score = features[0] + features[1] + 0.5 * features[2] + 0.2 * features[3]
    return {'score': score, 'features': features,
            'copy_bytes_proxy': detail['no_hit_copy_bytes'],
            'l2_hit_proxy': (detail['cache_request_proxy'] or {}).get('hit_bytes', 0)}


def shortlist(g, n, cfg, q):
    seeds = []
    for kind in ('depth_band', 'mask_band', 'valley_stage'):
        plan = stage_plan(g, n, kind)
        if plan is None:
            continue
        try:
            g.validate(plan, n)
            seeds.append({'name': kind, 'plan': plan, 'proxy': proxy(g, plan, cfg, q)})
        except ValueError:
            pass
    if not seeds:
        raise ValueError('no valid stage seed')
    seed = min(seeds, key=lambda r: (r['proxy']['score'], r['name']))
    proposed, failures = neighbors(g, seed['plan'], n)
    groups = {}
    for name, plan in proposed:
        kind = name.split('_s')[0]
        try:
            row = {'name': name, 'plan': plan, 'proxy': proxy(g, plan, cfg, q)}
            if kind not in groups or (row['proxy']['score'], name) < (groups[kind]['proxy']['score'], groups[kind]['name']):
                groups[kind] = row
        except ValueError as exc:
            failures.append({'move': name, 'reason': str(exc)})
    return [seed, *[groups[k] for k in ('migrate', 'split', 'swap') if k in groups]], failures
