"""Graph-only upper-risk indicator for long-lived on-core tensors.

It is an ordering proxy, not the official Step-2 memory allocator.
"""
from collections import defaultdict


def live_peak(problem, plan):
    mapping, assignment, groups = problem.view(plan)
    topo_groups = defaultdict(list)
    for op in problem.order:
        topo_groups[mapping[op]].append(op)
    positions = {}
    for core, schedule in enumerate(plan['core_schedules']):
        ordered = [op for sg in schedule for op in topo_groups[sg]]
        positions[core] = {op: i for i, op in enumerate(ordered)}
    changes = [{p: defaultdict(int) for p in ('L1', 'UB')} for _ in range(problem.n)]
    for tid, producers, consumers, _ in problem.tensor_views:
        t = problem.tensors[tid]
        place = t.get('pos', 'UB')
        if place == 'DDR':
            place = 'UB'
        if place not in ('L1', 'UB'):
            continue
        for core in range(problem.n):
            items = [positions[core][op] for op in producers + consumers
                     if op in positions[core]]
            if not items:
                continue
            first, last = min(items), max(items)
            changes[core][place][first] += t['size']
            changes[core][place][last + 1] -= t['size']
    peak = {p: 0 for p in ('L1', 'UB')}
    for core in range(problem.n):
        for place in peak:
            live = 0
            for i in sorted(changes[core][place]):
                live += changes[core][place][i]
                peak[place] = max(peak[place], live)
    return peak
