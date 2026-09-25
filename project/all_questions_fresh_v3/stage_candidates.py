"""Input-derived depth and ancestry partitions; no score or evaluator access.

Adapted from the user's previous legal depth-band construction. Widths now
depend only on current graph depth and core count. Every band is topologically
later than the preceding band; grouping therefore cannot reverse dependencies.
"""
from collections import Counter, defaultdict
from math import ceil


def split_dominated(g, n):
    work = g.work(g.ops)
    return any(max(g.work(part)) > max(work) / n for part in g.components)


def stage_plan(g, n, kind):
    depth = {}
    for v in g.order:
        depth[v] = 1 + max((depth[p] for p in g.pred[v]), default=0)
    height = max(depth.values(), default=0)
    width = max(1, ceil(height / (n if kind == 'depth_band' else 2*n)))
    if kind == 'valley_stage':
        level_width = Counter(depth.values())
        narrow = Counter(level_width.values()).most_common(1)[0][0]
        boundaries = []
        if narrow >= 2:
            for level in range(1, height):
                if (level_width[level] <= narrow) != (level_width[level+1] <= narrow):
                    boundaries.append(level)
        if not boundaries:
            return None
        boundaries.append(height)
        bands = defaultdict(set)
        b = 0
        for v in g.order:
            while depth[v] > boundaries[b]:
                b += 1
            bands[b].add(v)
        # Every band has its own fork/join structure. Shared ancestors are
        # placed first; private branches follow with local load balance.
        mapping, schedules, sgid = {}, [[] for _ in range(n)], 0
        for b in sorted(bands):
            members = bands[b]
            sinks = sorted(v for v in members if not (g.succ[v] & members))
            mask = {v: 1 << i for i, v in enumerate(sinks)}
            for v in reversed(g.order):
                if v in members:
                    for w in g.succ[v] & members:
                        mask[v] = mask.get(v, 0) | mask[w]
            shared = {v for v in members if mask[v].bit_count() > 1}
            private = defaultdict(list)
            for v in members - shared:
                private[mask[v]].append(v)
            loads = [[0, 0] for _ in range(n)]
            for pieces in (g.connected(shared), list(private.values())):
                chosen = defaultdict(list)
                for part in sorted(pieces, key=lambda x: (-max(g.work(x)), min(x))):
                    pair = g.work(part)
                    c = min(range(n), key=lambda c: (max(loads[c][0]+pair[0], loads[c][1]+pair[1]),
                                                    sum(loads[c]), c))
                    chosen[c].extend(part)
                    loads[c][0] += pair[0]; loads[c][1] += pair[1]
                for c in sorted(chosen):
                    for v in chosen[c]: mapping[str(v)] = sgid
                    schedules[c].append(sgid); sgid += 1
        return {'node_to_subgraph': mapping, 'core_schedules': schedules}
    if kind == 'mask_band':
        sinks = [v for v in g.order if not g.succ[v]]
        mask = {v: 1 << i for i, v in enumerate(sinks)}
        for v in reversed(g.order):
            for w in g.succ[v]:
                mask[v] = mask.get(v, 0) | mask[w]
    else:
        mask = dict.fromkeys(g.ops, 0)
    buckets = defaultdict(set)
    for v in g.ops:
        buckets[((depth[v]-1)//width, mask[v])].add(v)
    mapping, schedules, sgid = {}, [[] for _ in range(n)], 0
    loads = [[0, 0] for _ in range(n)]
    last_band = -1
    for band, key in sorted(buckets, key=lambda x: (x[0], -x[1].bit_count(), x[1])):
        if band != last_band:
            loads = [[0, 0] for _ in range(n)]
            last_band = band
        pieces = g.connected(buckets[band, key])
        assignment = defaultdict(list)
        for part in sorted(pieces, key=lambda x: (-max(g.work(x)), min(x))):
            pair = g.work(part)
            c = min(range(n), key=lambda c: (max(loads[c][0]+pair[0], loads[c][1]+pair[1]),
                                            sum(loads[c]), c))
            assignment[c].extend(part)
            loads[c][0] += pair[0]
            loads[c][1] += pair[1]
        for c in sorted(assignment):
            for v in assignment[c]:
                mapping[str(v)] = sgid
            schedules[c].append(sgid)
            sgid += 1
    return {'node_to_subgraph': mapping, 'core_schedules': schedules}
