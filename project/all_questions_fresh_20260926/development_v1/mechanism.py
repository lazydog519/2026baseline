"""Analytical screening model, NOT the official execution simulator.

FIFO transitions below are exact for a supplied exogenous request trace.
That trace is estimated from compute dependencies, not the official allocator.
Logical live intervals are a pressure proxy, not a feasibility certificate.
"""
from collections import defaultdict, deque
import heapq


def topo(pred, succ):
    degree = {v: len(p) for v, p in pred.items()}
    ready = [v for v in pred if not degree[v]]
    heapq.heapify(ready)
    order = []
    while ready:
        v = heapq.heappop(ready)
        order.append(v)
        for w in sorted(succ[v]):
            degree[w] -= 1
            if not degree[w]:
                heapq.heappush(ready, w)
    if len(order) != len(pred):
        raise ValueError('cycle in analytical ordering')
    return order


def fifo_trace(requests, capacity, ddr_bw, l2_bw):
    """(issue_time, tensor_id, byte_size, is_read); two fair-sharing pools.

    Completions precede same-time issues; stable request index breaks ties.
    DDR writes do not populate cache. A hit does not refresh insertion order.
    No undocumented prefetched requests are created.
    """
    future = sorted((float(t), i, key, size, read) for i, (t, key, size, read) in enumerate(requests))
    index, now, used, hit_bytes, read_bytes, ddr_bytes = 0, 0., 0, 0, 0, 0
    entries, queue, pools = {}, deque(), [[], []]
    insertions, evictions, hits = 0, 0, 0
    while index < len(future) or pools[0] or pools[1]:
        next_issue = future[index][0] if index < len(future) else float('inf')
        ends = [now + min(x[0] for x in pool) * len(pool) / bw if pool else float('inf')
                for pool, bw in zip(pools, (ddr_bw, l2_bw))]
        nxt = min(next_issue, *ends)
        completed = []
        for p, (pool, bw) in enumerate(zip(pools, (ddr_bw, l2_bw))):
            if not pool:
                continue
            delta = (nxt - now) * bw / len(pool)
            for item in pool:
                item[0] -= delta
                if item[0] <= 1e-7:
                    completed.append((item[1], p, item))
            pools[p] = [x for x in pool if x[0] > 1e-7]
        now = nxt
        for _, p, (_, i, key, size, read) in sorted(completed):
            if p == 0 and read and key not in entries and size <= capacity:
                while queue and used + size > capacity:
                    used -= entries.pop(queue.popleft())
                    evictions += 1
                entries[key] = size
                queue.append(key)
                used += size
                insertions += 1
        while index < len(future) and future[index][0] <= now + 1e-9:
            _, i, key, size, read = future[index]
            hit = read and key in entries
            if read:
                read_bytes += size
            if hit:
                hit_bytes += size
                hits += 1
            else:
                ddr_bytes += size
            if size:
                pools[int(hit)].append([float(size), i, key, size, read])
            index += 1
    return dict(hit_bytes=hit_bytes, read_bytes=read_bytes, ddr_bytes=ddr_bytes,
                hits=hits, insertions=insertions, evictions=evictions, trace_end=now)


def describe(g, plan, cfg, question):
    n = len(plan['core_schedules'])
    mapping, assigned = g.validate(plan, n)
    core = {v: assigned[mapping[v]] for v in g.ops}
    task = mapping if question == 1 else core
    bw = cfg['bandwidth']['bandwidth']
    sync = cfg['multicore_scene_b']['cross_core_copy_delay_cycles']
    same = cfg['multicore_scene_a']['task_same_core_wait_cycles']
    cross = cfg['multicore_scene_a']['task_cross_core_wait_cycles']
    l2 = cfg['problem_3']
    groups = defaultdict(list)
    for v in g.order:
        groups[mapping[v]].append(v)
    seqs = [[v for s in seq for v in groups[s]] for seq in plan['core_schedules']]
    positions = [{v: i for i, v in enumerate(seq)} for seq in seqs]
    # Nominal compute pipeline order is only a proxy for Appendix C Step 1/3.
    pred = {v: set(g.pred[v]) for v in g.ops}
    succ = {v: set(g.succ[v]) for v in g.ops}
    for seq in seqs:
        last = {}
        for v in seq:
            p = g.ops[v]['pipe']
            if p in last:
                pred[v].add(last[p]); succ[last[p]].add(v)
            last[p] = v
    finish, start = {}, {}
    for v in topo(pred, succ):
        start[v] = max((finish[p] + (sync + 2 * g.edge_bytes[p, v] / bw
                       if core[p] != core[v] and p in g.pred[v] else 0)
                        for p in pred[v]), default=0)
        finish[v] = start[v] + g.ops[v]['cycles']
    core_work = [g.work(seq) for seq in seqs]
    floor = max([max(g.cp.values(), default=0)] + [max(w) for w in core_work])
    if question == 1:
        tp, ts = {s: set() for s in groups}, {s: set() for s in groups}
        waits = {}
        for v in g.order:
            for w in g.succ[v]:
                a, b = mapping[v], mapping[w]
                if a != b:
                    tp[b].add(a); ts[a].add(b)
                    waits[a, b] = cross if assigned[a] != assigned[b] else same
        for seq in plan['core_schedules']:
            for a, b in zip(seq, seq[1:]):
                tp[b].add(a); ts[a].add(b); waits[a, b] = max(same, waits.get((a, b), 0))
        end_task, internal_cp = {}, {}
        for v in g.order:
            internal_cp[v] = g.ops[v]['cycles'] + max((internal_cp[p] for p in g.pred[v]
                                                    if mapping[p] == mapping[v]), default=0)
        for s in topo(tp, ts):
            work = max(max(g.work(groups[s])), max(internal_cp[v] for v in groups[s]))
            end_task[s] = work + max((end_task[p] + waits[p, s] for p in tp[s]), default=0)
        floor = max(floor, max(end_task.values(), default=0))
    else:
        cp = {}
        for v in g.order:
            cp[v] = g.ops[v]['cycles'] + max((cp[p] + (sync if core[p] != core[v] else 0)
                                             for p in g.pred[v]), default=0)
        floor = max(floor, max(cp.values(), default=0))
    # Count communication per tensor and destination Task, not per graph edge.
    total, minimum, cross_bytes = 0, 0, 0
    requests = []
    events = defaultdict(lambda: defaultdict(lambda: {'L1': 0, 'UB': 0}))
    for t, tensor in g.tensors.items():
        size, pos = tensor['size'], tensor['pos']
        sources = {task[v] for v in g.producers[t]}
        users = defaultdict(list)
        for v in g.consumers[t]:
            users[task[v]].append(v)
        remote = set(users) - sources
        writes = int(bool(sources) and (bool(remote) or t in g.outputs))
        reads = len(remote)
        total += size * (writes + reads)
        cross_bytes += size * (writes + reads) if sources and remote else 0
        if question < 3 or size > l2['cache_capacity_bytes']:
            minimum += size * (writes + reads)
        else:
            minimum += size * (writes + int(reads > 0))
        if writes:
            requests.append((max(finish[v] for v in g.producers[t]), t, size, False))
        for k in sorted(remote):
            at = min(start[v] for v in users[k])
            if sources:
                at = max(at, max(finish[v] for v in g.producers[t]) + size / bw + sync)
            requests.append((at, t, size, True))
        if pos not in ('L1', 'UB'):
            continue
        for k in sources | set(users):
            vs = [v for v in g.producers[t] if task[v] == k]
            us = users.get(k, [])
            c = core[(vs or us)[0]]
            lo = min(positions[c][v] for v in vs or us)
            hi = max(positions[c][v] for v in us or vs)
            events[k][2 * lo][pos] += size
            events[k][2 * hi + 1][pos] -= size
    peak_rows = []
    for k, changes in events.items():
        live, peak = {'L1': 0, 'UB': 0}, {'L1': 0, 'UB': 0}
        for j in sorted(changes):
            for pos in live:
                live[pos] += changes[j][pos]; peak[pos] = max(peak[pos], live[pos])
        peak_rows.append({'task': k, **peak})
    excess = sum(max(0, row[pos] - cfg['capacity'][pos]) for row in peak_rows for pos in ('L1', 'UB'))
    fifo = fifo_trace(requests, l2['cache_capacity_bytes'], bw, l2['cache_bandwidth_bytes_per_cycle']) if question == 3 else None
    hit = fifo['hit_bytes'] if fifo else 0
    floor = max(floor, minimum / bw)
    nominal = max(finish.values(), default=0)
    features = [floor, max(0, nominal - floor), (total - hit) / bw,
                excess / bw, hit / l2['cache_bandwidth_bytes_per_cycle']]
    return features, dict(no_hit_copy_bytes=total, cross_task_copy_bytes=cross_bytes,
        minimum_ddr_bytes=minimum, physical_lower_bound_cycles=floor,
        logical_peak_bytes=peak_rows, logical_excess_bytes=excess,
        nominal_compute_end=nominal, cache_request_proxy=fifo,
        memory_feasibility='not certified by logical intervals')
