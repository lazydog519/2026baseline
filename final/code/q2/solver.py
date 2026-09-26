"""Scene B: independent graph-only inference; no official evaluator in this package."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from memory_proxy import live_peak
from model import Problem

FAMILIES = ('component', 'valley', 'data', 'data_wide', 'band')
RISK_MULTIPLIER = 10  # Global byte-equivalent spill risk; fixed before final generation.


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
            values['multicore_scene_b', 'cross_core_copy_delay_cycles'],
            {'L1': values['capacity', 'L1'], 'UB': values['capacity', 'UB']})


def validate(problem, plan):
    if set(plan) != {'node_to_subgraph', 'core_schedules'}:
        raise ValueError('output fields')
    if len(plan['core_schedules']) != problem.n:
        raise ValueError('core count')
    mapping, _, groups = problem.view(plan)
    if set(mapping) != set(problem.ops) or len(mapping) != len(plan['node_to_subgraph']):
        raise ValueError('compute op coverage')
    scheduled = [sg for seq in plan['core_schedules'] for sg in seq]
    if len(scheduled) != len(set(scheduled)) or set(scheduled) != set(groups):
        raise ValueError('subgraph coverage')
    succ, indeg = {sg: set() for sg in groups}, {sg: 0 for sg in groups}
    for p, targets in problem.succ.items():
        for c in targets:
            a, b = mapping[p], mapping[c]
            if a != b:
                succ[a].add(b)
    for seq in plan['core_schedules']:
        for a, b in zip(seq, seq[1:]):
            succ[a].add(b)
    for targets in succ.values():
        for sg in targets:
            indeg[sg] += 1
    ready = [sg for sg in groups if indeg[sg] == 0]
    visited = 0
    while ready:
        sg = ready.pop()
        visited += 1
        for nxt in succ[sg]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    if visited != len(groups):
        raise ValueError('subgraph/order cycle')


def solve(graph, cores, config):
    if cores not in (2, 3, 4, 5):
        raise ValueError('Scene B search uses 2–5 cores; single-core speedup is 1')
    bandwidth, delay, capacity = hardware(config)
    problem = Problem(graph, cores, bandwidth, delay, capacity)
    records, rejected, seen = [], [], set()
    for family in FAMILIES:
        try:
            plan = problem.construct(family)
            validate(problem, plan)
            digest = hashlib.sha256(json.dumps(plan, sort_keys=True,
                        separators=(',', ':')).encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            proxy, ddr, _ = problem.estimate(plan)
            peak = live_peak(problem, plan)
            # DDR work and excess live bytes are risk terms, not official time.
            risk = sum(max(0, peak[p]-capacity[p]) for p in ('L1', 'UB'))
            rank = proxy + (ddr+RISK_MULTIPLIER*risk)/bandwidth
            records.append(dict(family=family, plan=plan, proxy_cycles=proxy,
                                pre_spill_bytes=ddr, estimated_peak_bytes=peak,
                                risk_bytes=risk, rank_cycles=rank, digest=digest))
        except (ValueError, KeyError, RuntimeError, ZeroDivisionError) as exc:
            rejected.append(dict(family=family, error=str(exc)))
    if not records:
        raise RuntimeError(f'no legal candidate: {rejected}')
    best = min(records, key=lambda r: (r['rank_cycles'], r['pre_spill_bytes'],
                                       FAMILIES.index(r['family'])))
    return best['plan'], dict(selected=best['family'], plan_sha256=best['digest'],
                              risk_multiplier=RISK_MULTIPLIER,
                              candidates=[{k:v for k,v in r.items() if k != 'plan'}
                                          for r in records], rejected=rejected)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('graph', type=Path)
    ap.add_argument('-n', '--cores', type=int, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('-o', '--output', type=Path, required=True)
    ap.add_argument('--report', type=Path)
    args = ap.parse_args()
    start = time.perf_counter()
    graph = json.loads(args.graph.read_text(encoding='utf-8'))
    plan, report = solve(graph, args.cores, args.config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, separators=(',', ':'))+'\n', encoding='utf-8')
    if args.report:
        report['inference_seconds'] = time.perf_counter()-start
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
