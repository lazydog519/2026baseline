"""Development-only probe of graph-derived moves; never part of inference.

The baseline and the bounded move shortlist are frozen before any official
evaluation. No official result is used to change a plan within this run.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'all_questions_fresh_v3'
OFFICIAL = HERE.parent / 'official'
sys.path.insert(0, str(SOURCE))
from solver import Graph, read_hardware
from stage_candidates import stage_plan
from structural_neighbors import candidates as neighbors


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def proxy(g, plan, cfg, q):
    features, detail = g.features(plan, cfg, q)
    # Physical, untuned shortlist rule. This is not the contest objective.
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', nargs='+', default=['case_071', 'case_046'])
    ap.add_argument('--cores', type=int, default=5)
    ap.add_argument('--official', action='store_true')
    args = ap.parse_args()
    cfg = read_hardware(OFFICIAL / 'data' / 'config.txt')
    jobs = []
    for case in args.cases:
        raw = json.loads((OFFICIAL / 'data' / f'{case}.json').read_text(encoding='utf-8'))
        g = Graph(raw)
        for q in (1, 2, 3):
            picked, failures = shortlist(g, args.cores, cfg, q)
            for row in picked:
                jobs.append({'case': case, 'question': q, 'cores': args.cores,
                             'name': row['name'], 'plan_sha256': sha(row['plan']),
                             'proxy': row['proxy'], 'plan': row['plan'],
                             'generation_failures': failures})
    print(f'frozen_shortlist={len(jobs)}, cases={args.cases}', flush=True)
    if args.official:
        from experiment import compact, evaluate
        for i, job in enumerate(jobs, 1):
            raw = json.loads((OFFICIAL / 'data' / f"{job['case']}.json").read_text(encoding='utf-8'))
            start = time.perf_counter()
            try:
                job['official'] = {'status': 'ok', **compact(evaluate(job['question'], raw, job['plan']))}
            except Exception as exc:
                job['official'] = {'status': 'failed', 'reason': repr(exc)}
            job['official']['seconds'] = time.perf_counter() - start
            print(f"{i}/{len(jobs)} {job['case']} q{job['question']} {job['name']} "
                  f"{job['official'].get('makespan', job['official']['status'])}", flush=True)
    out = [{k: v for k, v in job.items() if k != 'plan'} for job in jobs]
    path = HERE / ('neighbor_official_probe.json' if args.official else 'neighbor_structural_probe.json')
    path.write_text(json.dumps({'scope': 'development-only bounded move probe',
                                'official_calls': len(out) if args.official else 0,
                                'shortlist_frozen_before_official': True,
                                'jobs': out}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(path, flush=True)


if __name__ == '__main__':
    main()
