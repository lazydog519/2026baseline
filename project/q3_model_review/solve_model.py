"""Q3 structural prototype. The generator never imports/calls official code.

The proxy is an approximation, not a feasibility certificate or a simulator.
Reuses only pure graph constructors from the earlier implementation.
"""
import argparse
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from heapq import heappop, heappush
from pathlib import Path

HERE = Path(__file__).resolve().parent
if not (HERE / 'q1_optimized.py').exists():
    sys.path.insert(0, str(HERE.parent / 'solution'))
from q1_optimized import compute_dag, topological_depth, first_join_plan, valley_stage_plan, depth_band_plan
from baseline import make_plan

VERSION = 'q3-structural-proxy-v1'


def hardware(path):
    result, section = {}, None
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.split('#')[0].strip()
        if not line:
            continue
        if line.startswith('['):
            section = line.strip('[]')
            result[section] = {}
        else:
            key, value = line.split()
            result[section][key] = int(value)
    return result


def topo(pred, succ, priority=None):
    degree = {v: len(p) for v, p in pred.items()}
    priority = priority or {v: (v,) for v in pred}
    ready = []
    for v in pred:
        if not degree[v]:
            heappush(ready, (priority[v], v))
    order = []
    while ready:
        _, v = heappop(ready)
        order.append(v)
        for w in sorted(succ[v]):
            degree[w] -= 1
            if not degree[w]:
                heappush(ready, (priority[w], w))
    if len(order) != len(pred):
        raise ValueError('dependency/schedule cycle')
    return order


class Model:
    def __init__(self, graph, cores, cfg):
        self.graph, self.n, self.cfg = graph, cores, cfg
        self.bw = cfg['bandwidth']['bandwidth']
        self.delay = cfg['multicore_scene_b']['cross_core_copy_delay_cycles']
        self.ops, self.pred, self.succ = compute_dag(graph)
        self.order, self.depth = topological_depth(self.ops, self.pred, self.succ)
        self.tensors = {t['id']: t for t in graph['tensors']}
        allops = {o['id']: o for o in graph['ops']}
        self.prod, self.cons = defaultdict(set), defaultdict(set)
        self.outputs = set()
        for e in graph['edges']:
            a, b = e['source'], e['target']
            if a in self.ops:
                self.prod[b].add(a)
            if b in self.ops:
                self.cons[a].add(b)
            if b in allops and allops[b]['op'] == 'COPY_OUT':
                self.outputs.add(a)
        self.components, seen = [], set()
        for root in self.order:
            if root in seen:
                continue
            todo, members = [root], []
            seen.add(root)
            while todo:
                v = todo.pop()
                members.append(v)
                for w in sorted(self.pred[v] | self.succ[v]):
                    if w not in seen:
                        seen.add(w)
                        todo.append(w)
            self.components.append(sorted(members))
        self.position = {v: i for i, v in enumerate(self.order)}
        self.edge_bytes = defaultdict(int)
        for t in self.tensors:
            for a in self.prod[t]:
                for b in self.cons[t]:
                    self.edge_bytes[a, b] += self.tensors[t]['size']

    def structure(self, plan, include_core_order=True):
        if set(plan) != {'node_to_subgraph', 'core_schedules'}:
            raise ValueError('output must contain exactly the two contest fields')
        mapping = {int(v): s for v, s in plan['node_to_subgraph'].items()}
        if len(mapping) != len(plan['node_to_subgraph']) or set(mapping) != set(self.ops):
            raise ValueError('operation coverage mismatch')
        if len(plan['core_schedules']) != self.n:
            raise ValueError('core count mismatch')
        flat = [s for seq in plan['core_schedules'] for s in seq]
        if len(flat) != len(set(flat)) or set(flat) != set(mapping.values()):
            raise ValueError('each nonempty subgraph must be assigned exactly once')
        if any(type(s) is not int or s < 0 for s in flat):
            raise ValueError('invalid subgraph id')
        assignment = {s: c for c, seq in enumerate(plan['core_schedules']) for s in seq}
        groups = defaultdict(list)
        for v, s in mapping.items():
            groups[s].append(v)
        pred, succ = {s: set() for s in flat}, {s: set() for s in flat}
        for v in self.order:
            for w in self.succ[v]:
                a, b = mapping[v], mapping[w]
                if a != b:
                    pred[b].add(a)
                    succ[a].add(b)
        if include_core_order:
            for seq in plan['core_schedules']:
                for a, b in zip(seq, seq[1:]):
                    pred[b].add(a)
                    succ[a].add(b)
        return mapping, assignment, groups, topo(pred, succ)

    def component_plan(self):
        groups = self.components
        load = [[0, 0] for _ in range(self.n)]
        resident_inputs = [set() for _ in range(self.n)]
        reads = [0] * self.n
        mapping, schedules = {}, [[] for _ in range(self.n)]
        weights = [[sum(self.ops[v]['cycles'] for v in g if self.ops[v]['pipe'] == p)
                    for p in ('PIPE_M', 'PIPE_V')] for g in groups]
        input_of = defaultdict(set)
        for t in self.tensors:
            if not self.prod[t]:
                for v in self.cons[t]:
                    input_of[v].add(t)
        for s in sorted(range(len(groups)), key=lambda s: (-max(weights[s]), min(groups[s]))):
            inputs = set().union(*(input_of[v] for v in groups[s]))
            def key(c):
                extra = sum(self.tensors[t]['size'] for t in inputs - resident_inputs[c])
                return (max(load[c][0] + weights[s][0], load[c][1] + weights[s][1],
                            (reads[c] + extra) / self.bw), extra, c)
            c = min(range(self.n), key=key)
            reads[c] += sum(self.tensors[t]['size'] for t in inputs - resident_inputs[c])
            resident_inputs[c].update(inputs)
            for p in range(2):
                load[c][p] += weights[s][p]
            schedules[c].append(s)
            mapping.update({str(v): s for v in groups[s]})
        return {'node_to_subgraph': mapping, 'core_schedules': schedules}

    def proxy(self, plan):
        mapping, assignment, groups, sg_order = self.structure(plan)
        core = {v: assignment[mapping[v]] for v in self.ops}
        load = [[0, 0] for _ in range(self.n)]
        for v, op in self.ops.items():
            load[core[v]][0 if op['pipe'] == 'PIPE_M' else 1] += op['cycles']
        byte_count, reuse_potential = 0, 0
        local_tensors = [dict() for _ in range(self.n)]
        local_order = [[] for _ in range(self.n)]
        for s in sg_order:
            local_order[assignment[s]].extend(sorted(groups[s], key=self.position.get))
        local_pos = [{v: i for i, v in enumerate(seq)} for seq in local_order]
        for t, tensor in self.tensors.items():
            sources = {core[v] for v in self.prod[t]}
            destinations = {core[v] for v in self.cons[t]}
            if len(sources) > 1:
                raise ValueError('prototype needs single-core producer per tensor')
            size = tensor['size']
            if not sources:
                byte_count += size * len(destinations)
                if size <= self.cfg['problem_3']['cache_capacity_bytes']:
                    reuse_potential += size * max(0, len(destinations) - 1)
            else:
                remote = destinations - sources
                byte_count += size * (len(remote) + int(bool(remote) or t in self.outputs))
            for c in sources | destinations:
                uses = [local_pos[c][v] for v in self.cons[t] if core[v] == c]
                definitions = [local_pos[c][v] for v in self.prod[t] if core[v] == c]
                if not uses and not definitions:
                    continue
                first = min(definitions or uses)
                last = max(uses or definitions)
                if tensor['pos'] in ('L1', 'UB'):
                    local_tensors[c][t] = (first, last, tensor['pos'], size)
        finish = {}
        for v in self.order:
            finish[v] = self.ops[v]['cycles'] + max((finish[p] + (
                self.delay + 2 * self.edge_bytes[p, v] / self.bw if core[p] != core[v] else 0)
                for p in self.pred[v]), default=0)
        peaks = []
        for c in range(self.n):
            events = defaultdict(lambda: {'L1': 0, 'UB': 0})
            for first, last, pos, size in local_tensors[c].values():
                # Reserve output before freeing the inputs of the same operation.
                events[2 * first][pos] += size
                events[2 * last + 1][pos] -= size
            live, peak = {'L1': 0, 'UB': 0}, {'L1': 0, 'UB': 0}
            for index in sorted(events):
                for pos in live:
                    live[pos] += events[index][pos]
                    peak[pos] = max(peak[pos], live[pos])
            peaks.append(peak)
        excess = sum(max(0, peak[p] - self.cfg['capacity'][p]) for peak in peaks for p in peak)
        bottleneck = max(max((max(x) for x in load), default=0),
                         max(finish.values(), default=0), byte_count / self.bw)
        # A screening penalty, not a lower bound nor a predicted spill count.
        score = bottleneck + 2 * excess / self.bw
        return {'score_cycles': score, 'no_hit_read_write_bytes': byte_count,
                'input_cache_reuse_opportunity_bytes': reuse_potential,
                'logical_live_peak_bytes': peaks, 'excess_live_bytes': excess,
                'compute_load_by_core': load, 'approx_path_cycles': max(finish.values(), default=0)}

    def solve(self):
        # Bounded mechanism ablation; no per-case tuning using official outcomes.
        seeds = [('component_vector', self.component_plan())]
        weights = [sum(self.ops[v]['cycles'] for v in g) for g in self.components]
        if weights and max(weights) > 1.25 * sum(weights) / self.n:
            seeds.append(('join_separation', first_join_plan(self.graph, self.n)))
            seeds.append(('valley_separation', valley_stage_plan(self.graph, self.n,
                split_shared=True, narrow_rule='mode', min_band_depth=6)))
            width = max(4, min(32, math.ceil(math.sqrt(max(self.depth.values(), default=1)))))
            seeds.append(('depth_partition', depth_band_plan(self.graph, self.n, width, data_aware=True)))
        candidates, seen = [], set()
        for name, plan in seeds:
            digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            try:
                estimate = self.proxy(plan)
                candidates.append({'name': name, 'plan': plan, 'estimate': estimate})
            except ValueError as exc:
                candidates.append({'name': name, 'error': str(exc)})
        feasible = [r for r in candidates if 'estimate' in r]
        best = min(feasible, key=lambda r: (r['estimate']['score_cycles'],
            r['estimate']['no_hit_read_write_bytes'], r['name']))
        return best['plan'], {'selected': best['name'], 'selected_proxy': best['estimate'],
            'candidates': [{k: v for k, v in r.items() if k != 'plan'} for r in candidates]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('graph', type=Path)
    ap.add_argument('-n', type=int, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('-o', type=Path)
    ap.add_argument('--report', type=Path)
    ap.add_argument('--method', choices=['fused', 'component_lpt'], default='fused')
    args = ap.parse_args()
    if not 1 <= args.n <= 5:
        ap.error('use 1..5 cores')
    start = time.perf_counter()
    graph = json.loads(args.graph.read_text(encoding='utf-8'))
    model = Model(graph, args.n, hardware(args.config))
    if args.method == 'component_lpt':
        plan = make_plan(graph, args.n)
        report = {'selected': 'component_lpt', 'selected_proxy': model.proxy(plan)}
    else:
        plan, report = model.solve()
    model.structure(plan)
    output = args.o or args.graph.with_name(args.graph.stem + '_multicore_res.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    report.update(version=VERSION, method=args.method, cores=args.n,
                  wall_seconds=time.perf_counter() - start,
                  graph_sha256=hashlib.sha256(args.graph.read_bytes()).hexdigest(),
                  config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
                  plan_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  official_calls_during_generation=0, random_seed=None,
                  structural_validation='pass', full_execution_validation='not_performed')
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('selected', 'wall_seconds', 'official_calls_during_generation')}))


if __name__ == '__main__':
    main()
