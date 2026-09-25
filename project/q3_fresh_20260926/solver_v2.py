"""Fresh Q3 solver: standard-library inference, no evaluator or past-result IO.

Only graph, hardware, and this round's global coefficients enter inference.
Structural safety is conservative: core dependencies must also be acyclic.
Memory-pressure features are estimates; no spill-free guarantee is asserted.
"""
import argparse
from collections import defaultdict
import hashlib
import heapq
import json
from pathlib import Path
import time

VERSION = 'fresh-q3-20260926-v2'
FEATURES = ['physical_lower_bound', 'cross_path_exposure', 'compulsory_io',
            'repeated_read_exposure', 'private_memory_pressure']
INITIAL_WEIGHTS = [1., 1., 1., 1., 2.]


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

    def build(self, n, mode):
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
            else:
                c = min(range(n), key=lambda c: (max(loads[c][0] + weights[s][0],
                    loads[c][1] + weights[s][1]), sum(loads[c]), c))
            cores[s] = c
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
        corepred, coresucc = {c: set() for c in range(n)}, {c: set() for c in range(n)}
        for v in self.order:
            for w in self.succ[v]:
                a, b = mapping[v], mapping[w]
                if a != b:
                    pred[b].add(a)
                    succ[a].add(b)
                ca, cb = assigned[a], assigned[b]
                if ca != cb:
                    corepred[cb].add(ca)
                    coresucc[ca].add(cb)
        for seq in plan['core_schedules']:
            for a, b in zip(seq, seq[1:]):
                pred[b].add(a)
                succ[a].add(b)
        topological(pred, succ)
        topological(corepred, coresucc)
        return mapping, assigned

    def features(self, plan, cfg):
        n = len(plan['core_schedules'])
        mapping, assigned = self.validate(plan, n)
        core = {v: assigned[mapping[v]] for v in self.ops}
        bw = cfg['bandwidth']['bandwidth']
        delay = cfg['multicore_scene_b']['cross_core_copy_delay_cycles']
        cache = cfg['problem_3']['cache_capacity_bytes']
        groups = defaultdict(list)
        for v in self.order:
            groups[mapping[v]].append(v)
        sequences = [[v for s in seq for v in groups[s]] for seq in plan['core_schedules']]
        positions = [{v: i for i, v in enumerate(seq)} for seq in sequences]
        load = [self.work(seq) for seq in sequences]
        bottleneck = max([max(self.cp.values(), default=0)] + [max(w) for w in load])
        exposed, sync_path = {}, {}
        for v in self.order:
            sync_path[v] = self.ops[v]['cycles'] + max((sync_path[p] + (
                delay if core[p] != core[v] else 0) for p in self.pred[v]), default=0)
            exposed[v] = self.ops[v]['cycles'] + max((exposed[p] + (
                delay + 2 * self.edge_bytes[p, v] / bw if core[p] != core[v] else 0)
                for p in self.pred[v]), default=0)
        total, repeat, minimum_ddr = 0, 0, 0
        events = [defaultdict(lambda: {'L1': 0, 'UB': 0}) for _ in range(n)]
        for t, tensor in self.tensors.items():
            size = tensor['size']
            sources = {core[v] for v in self.producers[t]}
            destinations = {core[v] for v in self.consumers[t]}
            if not sources:
                total += size * len(destinations)
                minimum_ddr += size * int(bool(destinations))
                if t in self.inputs and size <= cache:
                    repeat += size * max(0, len(destinations) - 1)
            else:
                remote = destinations - sources
                total += size * (len(remote) + int(bool(remote) or t in self.outputs))
                # Cache starts empty. A cross-core produced tensor needs one
                # DDR write and at least one DDR read; other cores may hit L2.
                minimum_ddr += size * (int(bool(remote)) + int(bool(remote) or t in self.outputs))
            if tensor['pos'] not in ('L1', 'UB'):
                continue
            for c in sources | destinations:
                defs = [positions[c][v] for v in self.producers[t] if core[v] == c]
                uses = [positions[c][v] for v in self.consumers[t] if core[v] == c]
                first, last = min(defs or uses), max(uses or defs)
                # Approximate sequential lifetime, including simultaneous input/output.
                events[c][2 * first][tensor['pos']] += size
                events[c][2 * last + 1][tensor['pos']] -= size
        peaks = []
        for changes in events:
            live, peak = {'L1': 0, 'UB': 0}, {'L1': 0, 'UB': 0}
            for index in sorted(changes):
                for pos in live:
                    live[pos] += changes[index][pos]
                    peak[pos] = max(peak[pos], live[pos])
            peaks.append(peak)
        pressure = sum(max(0, peak[p] - cfg['capacity'][p]) for peak in peaks for p in peak)
        floor = max(bottleneck, max(sync_path.values(), default=0), minimum_ddr / bw)
        values = [floor, max(0, max(exposed.values(), default=0) - floor),
                  (total - repeat) / bw, repeat / bw, pressure / bw]
        return values, {'no_hit_copy_bytes': total, 'repeat_opportunity_bytes': repeat,
                        'minimum_ddr_bytes': minimum_ddr, 'physical_lower_bound_cycles': floor,
                        'logical_peak_bytes': peaks, 'logical_excess_bytes': pressure}

    def candidates(self, n, cfg):
        result, seen = [], set()
        for mode in ('component_scalar', 'component_vector', 'join_tail', 'shared_prefix'):
            plan = self.build(n, mode)
            signature = json.dumps(plan, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            feature, detail = self.features(plan, cfg)
            result.append({'name': mode, 'plan': plan, 'features': feature, 'detail': detail})
        return result


def solve(raw, n, cfg, weights, method='trained'):
    graph = Graph(raw)
    candidates = graph.candidates(n, cfg)
    if method == 'component_scalar':
        selected = candidates[0]
    else:
        selected = min(candidates, key=lambda c: (max(c['features'][0], sum(a * b for a, b in zip(weights, c['features']))),
                                                  c['detail']['no_hit_copy_bytes'], c['name']))
    return selected, candidates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('graph', type=Path)
    ap.add_argument('-n', type=int, required=True)
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
    selected, candidates = solve(json.loads(args.graph.read_text(encoding='utf-8')), args.n,
                                  read_hardware(args.config), model['weights'], args.method)
    out = args.o or args.graph.with_name(args.graph.stem + '_multicore_res.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(selected['plan'], sort_keys=True), encoding='utf-8')
    report = {'solver_version': VERSION, 'selected': selected['name'], 'method': args.method,
              'official_calls': 0, 'graph_sha256': digest(args.graph), 'model_sha256': digest(args.model),
              'plan_sha256': digest(out), 'generation_seconds': time.perf_counter() - start,
              'structural_checks': 'pass', 'execution_audit': 'not_yet_run',
              'candidates': [{k: v for k, v in c.items() if k != 'plan'} for c in candidates]}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('selected', 'official_calls', 'generation_seconds')}))


if __name__ == '__main__':
    main()
