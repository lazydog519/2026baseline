"""Scene-B candidate construction and cheap graph-only screening quantities."""
import math
import statistics
from collections import defaultdict

from baseline import make_plan
from q1_optimized import compute_dag, depth_band_plan, topological_depth, valley_stage_plan


class Problem:
    def __init__(self, graph, cores, bandwidth, delay, capacity):
        self.graph, self.n = graph, cores
        self.bw, self.delay, self.capacity = bandwidth, delay, capacity
        self.ops, self.pred, self.succ = compute_dag(graph)
        self.order, self.depth = topological_depth(self.ops, self.pred, self.succ)
        self.tensors = {t['id']: t for t in graph['tensors']}
        producers, consumers, all_consumers = defaultdict(set), defaultdict(set), defaultdict(set)
        original_ops = {o['id']: o for o in graph['ops']}
        for edge in graph['edges']:
            if edge['source'] in self.tensors and edge['target'] in original_ops:
                all_consumers[edge['source']].add(edge['target'])
            if edge['source'] in self.ops and edge['target'] in self.tensors:
                producers[edge['target']].add(edge['source'])
            if edge['target'] in self.ops and edge['source'] in self.tensors:
                consumers[edge['source']].add(edge['target'])
        self.tensor_views = []
        for tid, tensor in self.tensors.items():
            ps, cs = sorted(producers[tid]), sorted(consumers[tid])
            if ps or cs:
                output = any(original_ops[o]['op'] == 'COPY_OUT' for o in all_consumers[tid])
                self.tensor_views.append((tid, ps, cs, output))
        levels = sorted({self.depth[o] for o in self.ops
                         if len(self.pred[o]) > 1 or len(self.succ[o]) > 1})
        gaps = [b-a for a, b in zip(levels, levels[1:]) if b > a]
        self.width = max(2, min(32, round(statistics.median(gaps)) if gaps else
                                math.ceil(math.sqrt(max(self.depth.values(), default=1)))))
        self.edge_bytes = defaultdict(int)
        for tid, ps, cs, _ in self.tensor_views:
            for p in ps:
                for c in cs:
                    self.edge_bytes[p, c] += self.tensors[tid]['size']
        self.direct_edges = []
        for edge in graph['edges']:
            p, c = edge['source'], edge['target']
            if p in self.ops and c in self.ops:
                size = max(0, int(edge.get('data_size', 0)))
                self.direct_edges.append((p, c, size))
                self.edge_bytes[p, c] += size

    def view(self, plan):
        mapping = {int(o): s for o, s in plan['node_to_subgraph'].items()}
        assignment = {s: c for c, seq in enumerate(plan['core_schedules']) for s in seq}
        groups = defaultdict(list)
        for op, sg in mapping.items():
            groups[sg].append(op)
        return mapping, assignment, groups

    def construct(self, family):
        if family == 'component':
            return make_plan(self.graph, self.n)
        if family == 'valley':
            return valley_stage_plan(self.graph, self.n, split_shared=True,
                                     narrow_rule='mode', min_band_depth=self.width)
        if family in ('data', 'data_wide'):
            return depth_band_plan(self.graph, self.n,
                                   width=self.width*(2 if family == 'data_wide' else 1),
                                   data_aware=True)
        if family == 'band':
            return depth_band_plan(self.graph, self.n, width=self.width, data_aware=False)
        raise ValueError(f'unknown candidate {family}')

    def estimate(self, plan):
        mapping, assignment, _ = self.view(plan)
        core = {op: assignment[sg] for op, sg in mapping.items()}
        load = [[0, 0] for _ in range(self.n)]
        for op, data in self.ops.items():
            load[core[op]][data['pipe'] == 'PIPE_V'] += data['cycles']
        transfer = 0
        for tid, ps, cs, output in self.tensor_views:
            sources, targets = {core[o] for o in ps}, {core[o] for o in cs}
            copies = (len(targets) if cs and not ps else 0)
            copies += len(sources) if ps and (output or not cs) else 0
            copies += 2*sum(x != y for x in sources for y in targets)
            transfer += copies*self.tensors[tid]['size']
        transfer += 2*sum(size for p, c, size in self.direct_edges if core[p] != core[c])
        finish = {}
        for op in self.order:
            finish[op] = self.ops[op]['cycles'] + max((
                finish[p] + (self.delay + 2*self.edge_bytes[p, op]/self.bw
                             if core[p] != core[op] else 0)
                for p in self.pred[op]), default=0)
        proxy = max(max(map(max, load), default=0), max(finish.values(), default=0),
                    transfer/self.bw)
        return proxy, transfer, load
