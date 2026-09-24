"""Problem 1 graph partition candidates; original graph and evaluator stay unchanged."""

import argparse
import json
from collections import Counter, defaultdict
from bisect import bisect_left
from functools import partial
from heapq import heappop, heappush
from pathlib import Path

from baseline import make_plan as baseline_plan


def compute_dag(graph):
    ops = {op["id"]: op for op in graph["ops"]
           if op["op"] not in ("COPY_IN", "COPY_OUT")}
    producers, consumers = defaultdict(set), defaultdict(set)
    for edge in graph["edges"]:
        a, b = edge["source"], edge["target"]
        if a in ops:
            producers[b].add(a)
        if b in ops:
            consumers[a].add(b)
    pred = {oid: set() for oid in ops}
    succ = {oid: set() for oid in ops}
    for tid in producers.keys() & consumers.keys():
        for a in producers[tid]:
            for b in consumers[tid]:
                if a != b:
                    succ[a].add(b)
                    pred[b].add(a)
    # Direct Op-to-Op edges are accepted by the official evaluator as well.
    for edge in graph["edges"]:
        a, b = edge["source"], edge["target"]
        if a in ops and b in ops and a != b:
            succ[a].add(b)
            pred[b].add(a)
    return ops, pred, succ


def first_join_plan(graph, num_cores):
    """Keep independent pre-join branches intact; execute their join tail once."""
    ops, pred, succ = compute_dag(graph)
    tail = {oid for oid in ops if len(pred[oid]) > 1}
    pending = list(tail)
    while pending:
        for nxt in succ[pending.pop()]:
            if nxt not in tail:
                tail.add(nxt)
                pending.append(nxt)
    prefix = ops.keys() - tail
    if not prefix or not tail:
        return baseline_plan(graph, num_cores)

    parent = {oid: oid for oid in prefix}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in prefix:
        for b in succ[a] & prefix:
            x, y = find(a), find(b)
            if x != y:
                parent[max(x, y)] = min(x, y)
    components = defaultdict(list)
    for oid in prefix:
        components[find(oid)].append(oid)
    pieces = []
    for members in components.values():
        weight = [0, 0]
        for oid in members:
            op = ops[oid]
            weight[0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
        pieces.append((max(weight), min(members), members, weight))
    pieces.sort(key=lambda x: (-x[0], x[1]))
    load = [[0, 0] for _ in range(num_cores)]
    groups = [[] for _ in range(num_cores)]
    for _, _, members, weight in pieces:
        core = min(range(num_cores), key=lambda c:
                   (max(load[c][0] + weight[0], load[c][1] + weight[1]),
                    sum(load[c]), c))
        groups[core].extend(members)
        load[core][0] += weight[0]
        load[core][1] += weight[1]
    mapping = {str(oid): core for core, members in enumerate(groups)
               for oid in members}
    mapping.update({str(oid): num_cores for oid in tail})
    schedules = [[core] if members else []
                 for core, members in enumerate(groups)]
    schedules[0].append(num_cores)
    return {"node_to_subgraph": mapping, "core_schedules": schedules}


def topological_depth(ops, pred, succ):
    indeg = {oid: len(pred[oid]) for oid in ops}
    ready = []
    for oid, degree in indeg.items():
        if degree == 0:
            heappush(ready, oid)
    order, depth = [], {}
    while ready:
        oid = heappop(ready)
        order.append(oid)
        depth[oid] = 1 + max((depth[p] for p in pred[oid]), default=0)
        for nxt in succ[oid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heappush(ready, nxt)
    if len(order) != len(ops):
        raise ValueError("compute graph is cyclic")
    return order, depth


def terminal_branch_plan(graph, num_cores):
    """Run shared ancestors first, then independent output branches in parallel."""
    ops, pred, succ = compute_dag(graph)
    order, _ = topological_depth(ops, pred, succ)
    sinks = sorted(oid for oid in ops if not succ[oid])
    sink_bit = {oid: 0 for oid in ops}
    sink_bit.update({oid: 1 << i for i, oid in enumerate(sinks)})
    for oid in reversed(order):
        for nxt in succ[oid]:
            sink_bit[oid] |= sink_bit[nxt]
    shared = {oid for oid in ops if sink_bit[oid].bit_count() > 1}
    if not shared or len(shared) == len(ops):
        return baseline_plan(graph, num_cores)
    branches = defaultdict(list)
    for oid in ops.keys() - shared:
        branches[sink_bit[oid]].append(oid)
    pieces = []
    for bit, members in branches.items():
        work = [0, 0]
        for oid in members:
            op = ops[oid]
            work[0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
        pieces.append((max(work), bit, members, work))
    pieces.sort(key=lambda x: (-x[0], x[1]))
    load = [[0, 0] for _ in range(num_cores)]
    groups = [[] for _ in range(num_cores)]
    for _, _, members, work in pieces:
        core = min(range(num_cores), key=lambda c:
                   (max(load[c][0] + work[0], load[c][1] + work[1]),
                    sum(load[c]), c))
        groups[core].extend(members)
        load[core][0] += work[0]
        load[core][1] += work[1]
    mapping = {str(oid): num_cores for oid in shared}
    mapping.update({str(oid): core for core, members in enumerate(groups)
                    for oid in members})
    schedules = [[core] if members else []
                 for core, members in enumerate(groups)]
    schedules[0].insert(0, num_cores)
    return {"node_to_subgraph": mapping, "core_schedules": schedules}


def fork_join_plan(graph, num_cores):
    """Partition each fork/join epoch while preserving its global DAG order."""
    ops, pred, succ = compute_dag(graph)
    _, depth = topological_depth(ops, pred, succ)
    width = defaultdict(int)
    for level in depth.values():
        width[level] += 1
    last = max(width)
    boundaries = [d for d in range(1, last)
                  if width[d] == 1 and width[d + 1] > 1]
    if not boundaries:
        return baseline_plan(graph, num_cores)
    boundaries.append(last)
    mapping = {}
    schedules = [[] for _ in range(num_cores)]
    start, sgid = 1, 0
    for end in boundaries:
        epoch = {oid for oid in ops if start <= depth[oid] <= end}
        tail = {oid for oid in epoch if len(pred[oid] & epoch) > 1}
        pending = list(tail)
        while pending:
            for nxt in succ[pending.pop()] & epoch:
                if nxt not in tail:
                    tail.add(nxt)
                    pending.append(nxt)
        prefix = epoch - tail
        parent = {oid: oid for oid in prefix}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a in prefix:
            for b in succ[a] & prefix:
                x, y = find(a), find(b)
                if x != y:
                    parent[max(x, y)] = min(x, y)
        components = defaultdict(list)
        for oid in prefix:
            components[find(oid)].append(oid)
        pieces = []
        for members in components.values():
            weight = [0, 0]
            for oid in members:
                op = ops[oid]
                weight[0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
            pieces.append((max(weight), min(members), members, weight))
        pieces.sort(key=lambda x: (-x[0], x[1]))
        load = [[0, 0] for _ in range(num_cores)]
        groups = [[] for _ in range(num_cores)]
        for _, _, members, weight in pieces:
            core = min(range(num_cores), key=lambda c:
                       (max(load[c][0] + weight[0], load[c][1] + weight[1]),
                        sum(load[c]), c))
            groups[core].extend(members)
            load[core][0] += weight[0]
            load[core][1] += weight[1]
        for core, members in enumerate(groups):
            if members:
                mapping.update({str(oid): sgid for oid in members})
                schedules[core].append(sgid)
                sgid += 1
        if tail:
            mapping.update({str(oid): sgid for oid in tail})
            schedules[0].append(sgid)
            sgid += 1
        start = end + 1
    return {"node_to_subgraph": mapping, "core_schedules": schedules}


def depth_band_plan(graph, num_cores, width, data_aware=False):
    """Acyclic depth bands; independent regions in each band share a core Task."""
    if width < 1:
        raise ValueError("width must be positive")
    ops, pred, succ = compute_dag(graph)
    _, depth = topological_depth(ops, pred, succ)
    boundaries = []
    if data_aware:
        last = max(depth.values())
        difference = [0] * (last + 2)
        producers, consumers = defaultdict(list), defaultdict(list)
        for edge in graph["edges"]:
            if edge["source"] in ops:
                producers[edge["target"]].append(edge["source"])
            if edge["target"] in ops:
                consumers[edge["source"]].append(edge["target"])
        sizes = {tensor["id"]: tensor["size"]
                 for tensor in graph["tensors"]}
        for tid in producers.keys() & consumers.keys():
            for source in producers[tid]:
                for target in consumers[tid]:
                    a, b = depth[source], depth[target]
                    if a < b:
                        difference[a] += sizes[tid]
                        difference[b] -= sizes[tid]
        cut_bytes = [0] * (last + 1)
        running = 0
        for level in range(1, last):
            running += difference[level]
            cut_bytes[level] = running
        start = 0
        minimum = max(1, width // 2)
        maximum = max(minimum, width + width // 2)
        while last - start > maximum:
            choices = range(start + minimum,
                            min(start + maximum, last - minimum) + 1)
            end = min(choices, key=lambda level:
                      (cut_bytes[level], abs(level - start - width), level))
            boundaries.append(end)
            start = end
    bands = defaultdict(set)
    for oid, level in depth.items():
        bands[(bisect_left(boundaries, level) if data_aware else
               (level - 1) // width)].add(oid)
    mapping = {}
    schedules = [[] for _ in range(num_cores)]
    sgid = 0
    for band in sorted(bands):
        ids = bands[band]
        parent = {oid: oid for oid in ids}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a in ids:
            for b in succ[a] & ids:
                x, y = find(a), find(b)
                if x != y:
                    parent[max(x, y)] = min(x, y)
        components = defaultdict(list)
        for oid in ids:
            components[find(oid)].append(oid)
        pieces = []
        for members in components.values():
            weight = [0, 0]
            for oid in members:
                op = ops[oid]
                weight[0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
            pieces.append((max(weight), min(members), members, weight))
        pieces.sort(key=lambda x: (-x[0], x[1]))
        load = [[0, 0] for _ in range(num_cores)]
        groups = [[] for _ in range(num_cores)]
        for _, _, members, weight in pieces:
            core = min(range(num_cores), key=lambda c:
                       (max(load[c][0] + weight[0], load[c][1] + weight[1]),
                        sum(load[c]), c))
            groups[core].extend(members)
            load[core][0] += weight[0]
            load[core][1] += weight[1]
        for core, members in enumerate(groups):
            if members:
                mapping.update({str(oid): sgid for oid in members})
                schedules[core].append(sgid)
                sgid += 1
    return {"node_to_subgraph": mapping, "core_schedules": schedules}


def active_core_plan(make_plan, graph, num_cores, active_cores):
    """Use fewer than the available cores when DDR or Task overhead dominates."""
    if not 1 <= active_cores <= num_cores:
        raise ValueError("active_cores must be within available cores")
    plan = make_plan(graph, active_cores)
    plan["core_schedules"].extend([] for _ in range(num_cores - active_cores))
    return plan


def mask_band_plan(graph, num_cores, width=0, reset_load=False,
                   direction="sinks"):
    """Group equal ancestor/descendant masks in acyclic depth bands."""
    if width < 0:
        raise ValueError("width must be non-negative")
    if direction not in ("sinks", "sources"):
        raise ValueError("direction must be sinks or sources")
    ops, pred, succ = compute_dag(graph)
    order, depth = topological_depth(ops, pred, succ)
    if direction == "sinks":
        terminals = sorted(oid for oid in ops if not succ[oid])
        mask = {oid: 1 << i for i, oid in enumerate(terminals)}
        for oid in reversed(order):
            for nxt in succ[oid]:
                mask[oid] = mask.get(oid, 0) | mask[nxt]
    else:
        terminals = sorted(oid for oid in ops if not pred[oid])
        mask = {oid: 1 << i for i, oid in enumerate(terminals)}
        for oid in order:
            for nxt in succ[oid]:
                mask[nxt] = mask.get(nxt, 0) | mask[oid]
    buckets = defaultdict(set)
    for oid in ops:
        buckets[((depth[oid] - 1) // width if width else 0, mask[oid])].add(oid)
    mapping = {}
    schedules = [[] for _ in range(num_cores)]
    load = [[0, 0] for _ in range(num_cores)]
    sgid = 0
    previous_band = None
    sign = -1 if direction == "sinks" else 1
    for key in sorted(buckets, key=lambda k:
                      (k[0], sign * k[1].bit_count(), k[1])):
        if reset_load and key[0] != previous_band:
            load = [[0, 0] for _ in range(num_cores)]
        previous_band = key[0]
        ids = buckets[key]
        parent = {oid: oid for oid in ids}

        def find(oid):
            while parent[oid] != oid:
                parent[oid] = parent[parent[oid]]
                oid = parent[oid]
            return oid

        for oid in ids:
            for nxt in succ[oid] & ids:
                a, b = find(oid), find(nxt)
                if a != b:
                    parent[max(a, b)] = min(a, b)
        components = defaultdict(list)
        for oid in ids:
            components[find(oid)].append(oid)
        pieces = []
        for members in components.values():
            work = [0, 0]
            for oid in members:
                op = ops[oid]
                work[0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
            pieces.append((max(work), min(members), members, work))
        groups = [[] for _ in range(num_cores)]
        for _, _, members, work in sorted(pieces, key=lambda x: (-x[0], x[1])):
            core = min(range(num_cores), key=lambda c:
                       (max(load[c][0] + work[0], load[c][1] + work[1]),
                        sum(load[c]), c))
            groups[core].extend(members)
            load[core][0] += work[0]
            load[core][1] += work[1]
        for core, members in enumerate(groups):
            if members:
                mapping.update({str(oid): sgid for oid in members})
                schedules[core].append(sgid)
                sgid += 1
    return {"node_to_subgraph": mapping, "core_schedules": schedules}


def heft_task_schedule(graph, plan, num_cores, cross_wait=1000,
                       same_wait=100, bandwidth=60):
    """Schedule fixed legal Tasks by upward rank; do not reorder their Ops."""
    mapping = {int(oid): sg for oid, sg in plan["node_to_subgraph"].items()}
    task_ids = sorted(set(mapping.values()))
    load = {sg: [0, 0] for sg in task_ids}
    for op in graph["ops"]:
        sg = mapping.get(op["id"])
        if sg is not None:
            load[sg][0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
    weight = {sg: max(work) for sg, work in load.items()}
    _, _, succ_ops = compute_dag(graph)
    successors = {sg: set() for sg in task_ids}
    predecessors = {sg: set() for sg in task_ids}
    for oid, next_ops in succ_ops.items():
        source = mapping[oid]
        for nxt in next_ops:
            target = mapping[nxt]
            if source != target:
                successors[source].add(target)
                predecessors[target].add(source)
    producers, consumers = defaultdict(set), defaultdict(set)
    for edge in graph["edges"]:
        if edge["source"] in mapping:
            producers[edge["target"]].add(mapping[edge["source"]])
        if edge["target"] in mapping:
            consumers[edge["source"]].add(mapping[edge["target"]])
    sizes = {tensor["id"]: tensor["size"] for tensor in graph["tensors"]}
    transfer = defaultdict(int)
    for tid in producers.keys() & consumers.keys():
        for source in producers[tid]:
            for target in consumers[tid]:
                if source != target:
                    transfer[source, target] += sizes[tid]
    indegree = {sg: len(predecessors[sg]) for sg in task_ids}
    ready = [sg for sg in task_ids if indegree[sg] == 0]
    order = []
    while ready:
        sg = min(ready)
        ready.remove(sg)
        order.append(sg)
        for nxt in successors[sg]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(task_ids):
        raise ValueError("Task graph has a cycle")
    rank = {}
    for sg in reversed(order):
        rank[sg] = weight[sg] + max(
            (cross_wait + 2 * transfer[sg, nxt] / bandwidth + rank[nxt]
             for nxt in successors[sg]), default=0)
    schedules = [[] for _ in range(num_cores)]
    free = [0.0] * num_cores
    finished, placed = {}, {}
    for sg in sorted(task_ids, key=lambda s: (-rank[s], s)):
        def finish_on(core):
            start = max([free[core]] + [
                finished[p] + (same_wait if placed[p] == core else cross_wait)
                + 2 * transfer[p, sg] / bandwidth for p in predecessors[sg]])
            return start + weight[sg]
        core = min(range(num_cores), key=lambda c: (finish_on(c), c))
        free[core] = finish_on(core)
        finished[sg] = free[core]
        placed[sg] = core
        schedules[core].append(sg)
    return {"node_to_subgraph": plan["node_to_subgraph"],
            "core_schedules": schedules}


def valley_stage_plan(graph, num_cores, split_shared=False, affinity_cycles=0,
                      narrow_rule="minimum", min_band_depth=1):
    """Cut at DAG width valleys, then parallelize independent stage outputs."""
    ops, pred, succ = compute_dag(graph)
    order, depth = topological_depth(ops, pred, succ)
    width = defaultdict(int)
    for level in depth.values():
        width[level] += 1
    narrow = (min(width.values()) if narrow_rule == "minimum" else
              Counter(width.values()).most_common(1)[0][0]
              if narrow_rule == "mode" else None)
    if narrow is None:
        raise ValueError("narrow_rule must be minimum or mode")
    if narrow < 2:
        return baseline_plan(graph, num_cores)
    last = max(width)
    if min_band_depth < 1:
        raise ValueError("min_band_depth must be positive")
    boundaries = []
    previous = 0
    for level in range(1, last):
        if ((width[level] <= narrow) != (width[level + 1] <= narrow)
                and level - previous >= min_band_depth
                and last - level >= min_band_depth):
            boundaries.append(level)
            previous = level
    boundaries.append(last)
    if len(boundaries) < 2:
        return baseline_plan(graph, num_cores)
    bands = defaultdict(set)
    for oid, level in depth.items():
        bands[sum(level > b for b in boundaries)].add(oid)
    mapping = {}
    core_for_op = {}
    schedules = [[] for _ in range(num_cores)]
    sgid = 0
    for band in sorted(bands):
        ids = bands[band]
        local_sinks = sorted(oid for oid in ids if not (succ[oid] & ids))
        mask = {oid: 0 for oid in ids}
        mask.update({oid: 1 << i for i, oid in enumerate(local_sinks)})
        for oid in reversed(order):
            if oid in ids:
                for nxt in succ[oid] & ids:
                    mask[oid] |= mask[nxt]
        shared = {oid for oid in ids if mask[oid].bit_count() > 1}
        load = [[0, 0] for _ in range(num_cores)]
        if shared and split_shared:
            parent = {oid: oid for oid in shared}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            for oid in shared:
                for nxt in succ[oid] & shared:
                    a, b = find(oid), find(nxt)
                    if a != b:
                        parent[max(a, b)] = min(a, b)
            components = defaultdict(list)
            for oid in shared:
                components[find(oid)].append(oid)
            pieces = []
            for members in components.values():
                weight = [0, 0]
                for oid in members:
                    op = ops[oid]
                    weight[0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
                pieces.append((max(weight), min(members), members, weight))
            pieces.sort(key=lambda x: (-x[0], x[1]))
            shared_groups = [[] for _ in range(num_cores)]
            for _, _, members, weight in pieces:
                core = min(range(num_cores), key=lambda c:
                           (max(load[c][0] + weight[0], load[c][1] + weight[1]),
                            sum(load[c]), c))
                shared_groups[core].extend(members)
                load[core][0] += weight[0]
                load[core][1] += weight[1]
            for core, members in enumerate(shared_groups):
                if members:
                    mapping.update({str(oid): sgid for oid in members})
                    core_for_op.update({oid: core for oid in members})
                    schedules[core].append(sgid)
                    sgid += 1
        elif shared:
            mapping.update({str(oid): sgid for oid in shared})
            core_for_op.update({oid: 0 for oid in shared})
            schedules[0].append(sgid)
            sgid += 1
            for oid in shared:
                op = ops[oid]
                load[0][0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
        branches = defaultdict(list)
        for oid in ids - shared:
            branches[mask[oid]].append(oid)
        pieces = []
        for bit, members in branches.items():
            work = [0, 0]
            for oid in members:
                op = ops[oid]
                work[0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
            pieces.append((max(work), bit, members, work))
        pieces.sort(key=lambda x: (-x[0], x[1]))
        groups = [[] for _ in range(num_cores)]
        for _, _, members, work in pieces:
            ancestor_cores = {core_for_op[p] for oid in members
                              for p in pred[oid] if p in core_for_op}
            core = min(range(num_cores), key=lambda c:
                       (max(load[c][0] + work[0], load[c][1] + work[1])
                        + affinity_cycles * len(ancestor_cores - {c}),
                        sum(load[c]), c))
            groups[core].extend(members)
            core_for_op.update({oid: core for oid in members})
            load[core][0] += work[0]
            load[core][1] += work[1]
        for core, members in enumerate(groups):
            if members:
                mapping.update({str(oid): sgid for oid in members})
                schedules[core].append(sgid)
                sgid += 1
    return {"node_to_subgraph": mapping, "core_schedules": schedules}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("-n", "--num-cores", type=int, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--strategy", choices=("first_join", "terminal_branch", "fork_join", "valley_stage", "valley_mode", "band"),
                        default="first_join")
    parser.add_argument("--band-width", type=int, default=16)
    args = parser.parse_args()
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    strategy = {"first_join": first_join_plan,
                "terminal_branch": terminal_branch_plan,
                "fork_join": fork_join_plan,
                "valley_stage": valley_stage_plan,
                "valley_mode": partial(valley_stage_plan, split_shared=True,
                                       narrow_rule="mode")}.get(args.strategy)
    plan = (depth_band_plan(graph, args.num_cores, args.band_width)
            if args.strategy == "band" else strategy(graph, args.num_cores))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, separators=(",", ":")) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
