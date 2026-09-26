"""Scene A: graph-only candidate generation and deterministic selection.

This module never imports the official evaluator or reads case-specific history.
The separate development script may score its frozen candidate files.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from baseline import make_plan
from mechanistic import Model
from q1_optimized import (depth_band_plan, first_join_plan, fork_join_plan,
                          mask_band_plan, terminal_branch_plan, valley_stage_plan)


def signature(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate(model, plan, cores):
    """Check submitted fields, exact Op coverage, Task coverage and no order cycle."""
    if set(plan) != {'node_to_subgraph', 'core_schedules'} or len(plan['core_schedules']) != cores:
        raise ValueError('output schema or core count')
    mapping = plan['node_to_subgraph']
    if {int(x) for x in mapping} != set(model.ops):
        raise ValueError('compute Op coverage')
    flat = [s for seq in plan['core_schedules'] for s in seq]
    if len(flat) != len(set(flat)) or set(flat) != set(mapping.values()):
        raise ValueError('Task coverage or duplicate Task')
    model.estimate(plan)  # Raises for Task DAG or combined precedence/order cycle.


def candidates(graph, cores, bandwidth=60, same_wait=100, cross_wait=1000):
    if cores not in (2, 3, 4, 5):
        raise ValueError('Scene A optimizes only 2–5 cores')
    model = Model(graph, bandwidth, same_wait, cross_wait)
    depth = max(model.depth.values(), default=1)
    work = sum(o['cycles'] for o in model.ops.values())
    # Task granularity grows with actual graph depth and fixed wait cost.
    width = max(2, math.ceil(cores * cross_wait * depth / max(1, work)),
                math.ceil(depth * cores / 256))
    builders = [('component_vector', lambda: make_plan(graph, cores)),
                ('first_join', lambda: first_join_plan(graph, cores)),
                ('terminal_branch', lambda: terminal_branch_plan(graph, cores))]
    def fewer_cores(active):
        plan = make_plan(graph, active)
        plan['core_schedules'].extend([] for _ in range(cores-active))
        return plan
    for active in range(2, cores):
        builders.append((f'component_{active}_active', lambda active=active: fewer_cores(active)))
    for multiple in (1, 2, 4):
        w = width * multiple
        builders.extend([
            (f'data_band_{multiple}', lambda w=w: depth_band_plan(graph, cores, w, data_aware=True)),
            (f'fork_join_{multiple}', lambda w=w: fork_join_plan(graph, cores, min_band_depth=w)),
            (f'valley_{multiple}', lambda w=w: valley_stage_plan(graph, cores, split_shared=True,
                                                                  narrow_rule='mode', min_band_depth=w)),
            (f'mask_sink_{multiple}', lambda w=w: mask_band_plan(graph, cores, width=w,
                                                                  direction='sinks'))])
    builders.append(('mask_source', lambda: mask_band_plan(graph, cores, width=width,
                                                            direction='sources')))
    found, rejected, seen = [], [], set()
    for name, build in builders:
        try:
            plan = build()
            validate(model, plan, cores)
            sig = signature(plan)
            if sig in seen:
                continue
            seen.add(sig)
            view = model.describe(plan)
            estimated = model.estimate(plan, view)
            found.append(dict(name=name, plan=plan, fingerprint=sig, proxy_cycles=estimated,
                              boundary_bytes=view['bytes'], tasks=len(view['tasks']),
                              resource_floor=view['bound']))
        except (ValueError, KeyError, RuntimeError, ZeroDivisionError) as exc:
            rejected.append(dict(name=name, reason=str(exc)))
    # Scheduling and legal contraction are applied only to a small structural shortlist.
    for parent in sorted(found, key=lambda x: (x['proxy_cycles'], x['boundary_bytes']))[:3]:
        for suffix, transform in [('ready_schedule', lambda p: model.greedy(p)),
                                  ('local_merge', lambda p: model.coarsen(p, 2, 8))]:
            try:
                plan = transform(parent['plan'])
                validate(model, plan, cores)
                sig = signature(plan)
                if sig in seen:
                    continue
                seen.add(sig)
                view = model.describe(plan)
                found.append(dict(name=parent['name']+'_'+suffix, plan=plan,
                                  fingerprint=sig, proxy_cycles=model.estimate(plan, view),
                                  boundary_bytes=view['bytes'], tasks=len(view['tasks']),
                                  resource_floor=view['bound']))
            except (ValueError, KeyError, RuntimeError) as exc:
                rejected.append(dict(name=parent['name']+'_'+suffix, reason=str(exc)))
    if not found:
        raise RuntimeError('no structurally legal candidate')
    return found, rejected


def choose(rows, policy):
    """Fixed global coefficients learned in development; no evaluator at inference."""
    weight = policy['ddr_penalty_cycles_per_byte']
    task_penalty = policy['task_penalty_cycles']
    score = lambda r: r['proxy_cycles'] + weight * r['boundary_bytes'] + task_penalty * r['tasks']
    best = min(rows, key=lambda r: (score(r), r['boundary_bytes'], r['fingerprint']))
    component = next((r for r in rows if r['name'] == 'component_vector'), None)
    if component is not None and score(component) <= score(best) * (1 + policy['minimum_predicted_gain']):
        return component
    return best


def hardware(path):
    values, section = {}, None
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        else:
            key, value = line.split()
            values[section, key] = int(value)
    return (values['bandwidth', 'bandwidth'],
            values['multicore_scene_a', 'task_same_core_wait_cycles'],
            values['multicore_scene_a', 'task_cross_core_wait_cycles'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('graph', type=Path)
    parser.add_argument('-n', '--cores', type=int, required=True)
    parser.add_argument('-o', '--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--policy', type=Path, default=Path(__file__).with_name('policy.json'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    graph = json.loads(args.graph.read_text(encoding='utf-8'))
    policy = json.loads(args.policy.read_text(encoding='utf-8'))
    rows, rejected = candidates(graph, args.cores, *hardware(args.config))
    winner = choose(rows, policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(winner['plan'], separators=(',', ':'))+'\n', encoding='utf-8')
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(dict(selected=winner['name'], fingerprint=winner['fingerprint'],
                                               candidates=[{k:v for k,v in r.items() if k != 'plan'} for r in rows],
                                               rejected=rejected), indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
