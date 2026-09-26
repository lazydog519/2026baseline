"""Bounded graph-derived moves for a future cold solver; no evaluator import."""
from collections import defaultdict
import heapq
import json


def repair(g, mapping, core, n):
    groups = defaultdict(list)
    for v in g.order:
        groups[mapping[v]].append(v)
    pred = {s: set() for s in groups}
    succ = {s: set() for s in groups}
    for v in g.order:
        for w in g.succ[v]:
            a, b = mapping[v], mapping[w]
            if a != b:
                pred[b].add(a)
                succ[a].add(b)
    degree = {s: len(pred[s]) for s in groups}
    first = {s: min(g.position[v] for v in vs) for s, vs in groups.items()}
    ready = [(first[s], s) for s, d in degree.items() if d == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        _, s = heapq.heappop(ready)
        order.append(s)
        for t in sorted(succ[s]):
            degree[t] -= 1
            if degree[t] == 0:
                heapq.heappush(ready, (first[t], t))
    if len(order) != len(groups):
        raise ValueError('subgraph contraction cycle')
    schedules = [[] for _ in range(n)]
    for s in order:
        schedules[core[s]].append(s)
    plan = {'node_to_subgraph': {str(v): mapping[v] for v in g.ops},
            'core_schedules': schedules}
    g.validate(plan, n)
    return plan


def candidates(g, plan, n):
    mapping = {int(v): s for v, s in plan['node_to_subgraph'].items()}
    core = {s: k for k, seq in enumerate(plan['core_schedules']) for s in seq}
    groups = defaultdict(list)
    load = [[0, 0] for _ in range(n)]
    for v in g.order:
        s = mapping[v]
        groups[s].append(v)
        load[core[s]][0 if g.ops[v]['pipe'] == 'PIPE_M' else 1] += g.ops[v]['cycles']
    busy = max(range(n), key=lambda k: (max(load[k]), sum(load[k]), -k))
    targets = sorted((k for k in range(n) if k != busy),
                     key=lambda k: (max(load[k]), sum(load[k]), k))[:2]
    ranked = sorted((s for s in groups if core[s] == busy),
                    key=lambda s: (-max(g.work(groups[s])), -len(groups[s]), s))[:3]
    emitted, failures, seen = [], [], {json.dumps(plan, sort_keys=True)}

    def add(name, assignment, allocation):
        try:
            proposal = repair(g, assignment, allocation, n)
            signature = json.dumps(proposal, sort_keys=True)
            if signature not in seen:
                seen.add(signature)
                emitted.append((name, proposal))
        except ValueError as exc:
            failures.append({'move': name, 'reason': str(exc)})

    for s in ranked:
        for k in targets:
            alloc = dict(core)
            alloc[s] = k
            add(f'migrate_s{s}_to{k}', mapping, alloc)
    for s in ranked[:2]:
        vs = groups[s]
        if len(vs) < 4:
            continue
        choices = sorted(set((len(vs)//3, len(vs)//2, 2*len(vs)//3)))
        def cut_bytes(index):
            prefix = set(vs[:index])
            suffix = set(vs[index:])
            return sum(g.edge_bytes[u, v] for u in prefix for v in g.succ[u] if v in suffix)
        cut = min(choices, key=lambda index: (cut_bytes(index), abs(index-len(vs)/2)))
        for k in targets:
            new_id = max(core) + 1
            split = dict(mapping)
            for v in vs[cut:]:
                split[v] = new_id
            alloc = dict(core)
            alloc[new_id] = k
            add(f'split_s{s}_cut{cut}_to{k}', split, alloc)
    if ranked and targets:
        other = sorted((s for s in groups if core[s] == targets[0]),
                       key=lambda s: (-max(g.work(groups[s])), s))[:2]
        for a in ranked[:2]:
            for b in other:
                alloc = dict(core)
                alloc[a], alloc[b] = alloc[b], alloc[a]
                add(f'swap_s{a}_s{b}', mapping, alloc)
    return emitted[:14], failures
