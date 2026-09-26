"""Three-scene structural solver: no evaluator or historical-result IO.

Only graph, hardware, and this round's global coefficients enter inference.
Structural safety is conservative: core dependencies must also be acyclic.
Memory-pressure features are estimates; no spill-free guarantee is asserted.
"""
import argparse
from collections import defaultdict, deque
import hashlib
import heapq
import json
from pathlib import Path
import time

VERSION = 'fresh-all-20260926-v3'
FEATURES = ['resource_floor', 'nominal_schedule_excess', 'estimated_ddr_time',
            'logical_memory_excess_time', 'estimated_l2_time']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_hardware(path):
    cfg, section = {}, None
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.split('#')[0].strip()
        if not line:
            continue
        if line.startswith('['):
            section = line[1:-1]
            cfg[section] = {}
        else:
            key, value = line.split()
            cfg[section][key] = int(value)
    return cfg


def topological(pred, succ):
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
        raise ValueError('dependency cycle')
    return order


class Graph:
    def __init__(self, raw):
        self.raw = raw
        self.ops = {o['id']: o for o in raw['ops'] if o['op'] not in ('COPY_IN', 'COPY_OUT')}
        self.tensors = {t['id']: t for t in raw['tensors']}
        self.producers, self.consumers = defaultdict(set), defaultdict(set)
        self.outputs, self.inputs = set(), set()
        allops = {o['id']: o for o in raw['ops']}
        if any(e['source'] in allops and e['target'] in allops for e in raw['edges']):
            raise ValueError('input outside this version: direct Op-Op edges; actual 100 inputs contain none')
        for e in raw['edges']:
            a, b = e['source'], e['target']
            if a in self.ops:
                self.producers[b].add(a)
            if b in self.ops:
                self.consumers[a].add(b)
            if b in allops and allops[b]['op'] == 'COPY_OUT':
                self.outputs.add(a)
            if a in allops and allops[a]['op'] == 'COPY_IN':
                self.inputs.add(b)
        self.pred = {v: set() for v in self.ops}
        self.succ = {v: set() for v in self.ops}
        self.edge_bytes = defaultdict(int)
        for t in self.tensors:
            if len(self.producers[t]) > 1:
                raise ValueError('this prototype requires one compute producer per tensor')
            for a in self.producers[t]:
                for b in self.consumers[t]:
                    self.pred[b].add(a)
                    self.succ[a].add(b)
                    self.edge_bytes[a, b] += self.tensors[t]['size']
        self.outputs.update(t for t in self.tensors if self.producers[t] and not self.consumers[t])
        self.order = topological(self.pred, self.succ)
        self.position = {v: i for i, v in enumerate(self.order)}
        self.components = self.connected(set(self.ops))
        self.cp = {}
        for v in self.order:
            self.cp[v] = self.ops[v]['cycles'] + max((self.cp[p] for p in self.pred[v]), default=0)

    def connected(self, vertices):
        seen, result = set(), []
        for v in sorted(vertices):
            if v in seen:
                continue
            todo, group = [v], []
            seen.add(v)
            while todo:
                u = todo.pop()
                group.append(u)
                for w in sorted((self.pred[u] | self.succ[u]) & vertices):
                    if w not in seen:
                        seen.add(w)
                        todo.append(w)
            result.append(sorted(group))
        return result

    def work(self, group):
        return [sum(self.ops[v]['cycles'] for v in group if self.ops[v]['pipe'] == p)
                for p in ('PIPE_M', 'PIPE_V')]

    def profile(self):
        total = self.work(self.ops)
        return {'compute_ops': len(self.ops), 'weak_components': len(self.components),
                'largest_component_fraction': max(map(len, self.components), default=0) / max(1, len(self.ops)),
                'vector_share': total[1] / max(1, sum(total)),
                'compute_cycles': sum(total), 'critical_path_cycles': max(self.cp.values(), default=0),
                'shared_input_tensors': sum(len(self.consumers[t]) > 1 for t in self.inputs)}

    def build(self, n, mode, cfg=None):
        groups = [list(c) for c in self.components]
        fixed = None
        if mode == 'join_tail':
            tail = {v for v in self.ops if len(self.pred[v]) > 1}
            todo = list(tail)
            while todo:
                for w in self.succ[todo.pop()]:
                    if w not in tail:
                        tail.add(w)
                        todo.append(w)
            if tail and tail != set(self.ops):
                groups = self.connected(set(self.ops) - tail) + [sorted(tail)]
                fixed = (len(groups) - 1, n - 1)
        elif mode == 'shared_prefix':
            sinks = [v for v in self.order if not self.succ[v]]
            labels = {v: 1 << i for i, v in enumerate(sinks)}
            for v in reversed(self.order):
                if v not in labels:
                    labels[v] = 0
                    for w in self.succ[v]:
                        labels[v] |= labels[w]
            shared = {v for v in self.ops if labels[v].bit_count() > 1}
            if shared and shared != set(self.ops):
                groups = [sorted(shared)] + self.connected(set(self.ops) - shared)
                fixed = (0, 0)
        weights = [self.work(g) for g in groups]
        loads = [[0, 0] for _ in range(n)]
        group_inputs = [set() for _ in groups]
        if mode == 'component_affinity':
            membership = {v: s for s, group in enumerate(groups) for v in group}
            for t in self.inputs:
                for v in self.consumers[t]:
                    group_inputs[membership[v]].add(t)
        resident_inputs = [set() for _ in range(n)]
        cores = {}
        if fixed:
            s, c = fixed
            cores[s] = c
            loads[c] = weights[s][:]
        size_key = sum if mode == 'component_scalar' else max
        for s in sorted(range(len(groups)), key=lambda s: (-size_key(weights[s]), min(groups[s]))):
            if s in cores:
                continue
            if mode == 'component_scalar':
                c = min(range(n), key=lambda c: (sum(loads[c]), c))
            elif mode == 'component_affinity':
                c = min(range(n), key=lambda c: (max(loads[c][0] + weights[s][0], loads[c][1] + weights[s][1]) +
                    sum(self.tensors[t]['size'] for t in resident_inputs[c] | group_inputs[s]) / cfg['bandwidth']['bandwidth'], c))
            else:
                c = min(range(n), key=lambda c: (max(loads[c][0] + weights[s][0],
                    loads[c][1] + weights[s][1]), sum(loads[c]), c))
            cores[s] = c
            resident_inputs[c].update(group_inputs[s])
            loads[c] = [a + b for a, b in zip(loads[c], weights[s])]
        mapping = {str(v): s for s, group in enumerate(groups) for v in group}
        pred, succ = {s: set() for s in cores}, {s: set() for s in cores}
        for v in self.order:
            for w in self.succ[v]:
                a, b = mapping[str(v)], mapping[str(w)]
                if a != b:
                    pred[b].add(a)
                    succ[a].add(b)
        schedules = [[] for _ in range(n)]
        # A topological order projected to cores is the only submitted ordering.
        for s in topological(pred, succ):
            schedules[cores[s]].append(s)
        plan = {'node_to_subgraph': mapping, 'core_schedules': schedules}
        self.validate(plan, n)
        return plan

    def validate(self, plan, n):
        if set(plan) != {'node_to_subgraph', 'core_schedules'}:
            raise ValueError('unexpected output field')
        mapping = {int(v): s for v, s in plan['node_to_subgraph'].items()}
        if len(mapping) != len(plan['node_to_subgraph']) or set(mapping) != set(self.ops):
            raise ValueError('incorrect operation coverage')
        flat = [s for seq in plan['core_schedules'] for s in seq]
        if len(plan['core_schedules']) != n or len(flat) != len(set(flat)) or set(flat) != set(mapping.values()):
            raise ValueError('incorrect core/subgraph assignment')
        if any(type(s) is not int or s < 0 for s in flat):
            raise ValueError('invalid sgid')
        assigned = {s: c for c, seq in enumerate(plan['core_schedules']) for s in seq}
        pred, succ = {s: set() for s in flat}, {s: set() for s in flat}
        for v in self.order:
            for w in self.succ[v]:
                a, b = mapping[v], mapping[w]
                if a != b:
                    pred[b].add(a)
                    succ[a].add(b)
        for seq in plan['core_schedules']:
            for a, b in zip(seq, seq[1:]):
                pred[b].add(a)
                succ[a].add(b)
        topological(pred, succ)
        # The official interface permits alternating dependencies between
        # cores when the complete subgraph/order graph stays acyclic.
        return mapping, assigned

    def features(self, plan, cfg, question):
        from mechanism import describe
        return describe(self, plan, cfg, question)

    def variants(self, n, cfg, question):
        from stage_candidates import split_dominated, stage_plan
        if n > 1 and split_dominated(self, n):
            for name in ('depth_band', 'mask_band', 'valley_stage'):
                plan = stage_plan(self, n, name)
                if plan is None:
                    continue
                self.validate(plan, n)
                yield name, plan
        for mode in ('component_scalar', 'component_vector', 'component_affinity', 'join_tail', 'shared_prefix'):
            plan = self.build(n, mode, cfg)
            yield mode, plan
            if question == 1:
                # Coalescing is legal only if the contracted graph stays acyclic.
                core = {s: c for c, seq in enumerate(plan['core_schedules']) for s in seq}
                merged = {'node_to_subgraph': {v: core[s] for v, s in plan['node_to_subgraph'].items()},
                          'core_schedules': [[c] if seq else [] for c, seq in enumerate(plan['core_schedules'])]}
                yield mode + '_coalesced', merged
            elif mode in ('component_vector', 'component_affinity'):
                # Reorder independent components using shared-input affinity;
                # this changes legal subgraph order, never operation IDs or edges.
                by_group = defaultdict(set)
                for t in self.inputs:
                    for v in self.consumers[t]:
                        by_group[plan['node_to_subgraph'][str(v)]].add(t)
                sequences = []
                for seq in plan['core_schedules']:
                    todo, ordered, last = set(seq), [], set()
                    while todo:
                        s = min(todo, key=lambda s: (-sum(self.tensors[t]['size'] for t in by_group[s] & last), s))
                        ordered.append(s); todo.remove(s); last = by_group[s]
                    sequences.append(ordered)
                yield mode + '_reuse_order', {'node_to_subgraph': plan['node_to_subgraph'], 'core_schedules': sequences}

    def candidates(self, n, cfg, question):
        result, seen = [], set()
        for mode, plan in self.variants(n, cfg, question):
            signature = json.dumps(plan, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            feature, detail = self.features(plan, cfg, question)
            result.append({'name': mode, 'plan': plan, 'features': feature, 'detail': detail})
        return result


def solve(raw, n, cfg, weights, question, method='trained'):
    graph = Graph(raw)
    candidates = graph.candidates(n, cfg, question)
    if method == 'component_scalar':
        selected = next(c for c in candidates if c['name'] == 'component_scalar')
    else:
        selected = min(candidates, key=lambda c: (max(c['features'][0], sum(a * b for a, b in zip(weights, c['features']))),
                                                  c['detail']['no_hit_copy_bytes'], c['name']))
    return selected, candidates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('graph', type=Path)
    ap.add_argument('-n', type=int, required=True)
    ap.add_argument('--question', type=int, choices=(1, 2, 3), required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('-o', type=Path)
    ap.add_argument('--report', type=Path)
    ap.add_argument('--method', choices=['trained', 'component_scalar'], default='trained')
    args = ap.parse_args()
    if not 1 <= args.n <= 5:
        ap.error('core count must be in 1..5')
    start = time.perf_counter()
    model = json.loads(args.model.read_text(encoding='utf-8'))
    if model['solver_version'] != VERSION or model['features'] != FEATURES:
        raise ValueError('model schema mismatch')
    if digest(args.config) != model['hardware_sha256']:
        raise ValueError('use the unchanged official config.txt for this frozen model')
    selected, candidates = solve(json.loads(args.graph.read_text(encoding='utf-8')), args.n,
                                  read_hardware(args.config), model['weights'][str(args.question)], args.question, args.method)
    out = args.o or args.graph.with_name(args.graph.stem + '_multicore_res.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(selected['plan'], sort_keys=True), encoding='utf-8')
    report = {'solver_version': VERSION, 'selected': selected['name'], 'method': args.method,
              'question': args.question, 'official_calls': 0, 'graph_sha256': digest(args.graph), 'model_sha256': digest(args.model),
              'plan_sha256': digest(out), 'generation_seconds': time.perf_counter() - start,
              'structural_checks': 'pass', 'execution_audit': 'not_yet_run',
              'candidates': [{k: v for k, v in c.items() if k != 'plan'} for c in candidates]}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('selected', 'official_calls', 'generation_seconds')}))


if __name__ == '__main__':
    main()
