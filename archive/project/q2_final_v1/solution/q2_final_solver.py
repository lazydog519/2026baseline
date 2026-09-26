"""Standalone scene-B solver. No saved plan, case-name lookup or cross-case state.

Only input graph, fixed official config and search_config.json are read.
Surrogates rank candidates; the unchanged official simulator accepts solutions.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from heapq import heappop, heappush
from pathlib import Path

from q2_final_baseline import make_plan
from q2_final_graph import compute_dag, topological_depth, depth_band_plan, valley_stage_plan

VERSION = "q2-cilc-v1"
DEFAULT_CONFIG = Path(__file__).with_name("q2_final_config.json")


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


class Problem:
    def __init__(self, graph, cores, bandwidth, delay, capacity):
        self.graph, self.n, self.bw, self.delay, self.capacity = graph, cores, bandwidth, delay, capacity
        self.ops, self.pred, self.succ = compute_dag(graph)
        self.order, self.depth = topological_depth(self.ops, self.pred, self.succ)
        self.tensors = {t["id"]: t for t in graph["tensors"]}
        prod, cons = defaultdict(set), defaultdict(set)
        allops = {o["id"]: o for o in graph["ops"]}
        for e in graph["edges"]:
            if e["source"] in allops:
                prod[e["target"]].add(e["source"])
            if e["target"] in allops:
                cons[e["source"]].add(e["target"])
        self.tensor_views = []
        for tid, t in self.tensors.items():
            ps, cs = prod[tid] & self.ops.keys(), cons[tid] & self.ops.keys()
            if ps or cs:
                output = any(allops[o]["op"] == "COPY_OUT" for o in cons[tid])
                self.tensor_views.append((tid, sorted(ps), sorted(cs), output))
        levels = sorted({self.depth[o] for o in self.ops
                         if len(self.pred[o]) > 1 or len(self.succ[o]) > 1})
        gaps = [b-a for a, b in zip(levels, levels[1:]) if b>a]
        self.initial_width = max(2, min(32, round(statistics.median(gaps)) if gaps
                                       else math.ceil(math.sqrt(max(self.depth.values(), default=1)))))
        self.edge_bytes = defaultdict(int)
        for tid, ps, cs, _ in self.tensor_views:
            for p in ps:
                for c in cs:
                    self.edge_bytes[p, c] += self.tensors[tid]["size"]
        cp = {}
        for o in self.order:
            cp[o] = self.ops[o]["cycles"] + max((cp[p] for p in self.pred[o]), default=0)
        self.compute_path_bound = max(cp.values(), default=0)
        self.component = {}
        for root in sorted(self.ops):
            if root in self.component:
                continue
            self.component[root] = root
            stack = [root]
            while stack:
                o = stack.pop()
                for nxt in sorted(self.pred[o] | self.succ[o]):
                    if nxt not in self.component:
                        self.component[nxt] = root
                        stack.append(nxt)

    def locality_profile(self, plan):
        mapping, assignment, groups = self.view(plan)
        core = {o: assignment[s] for o, s in mapping.items()}
        total = 0
        internal = 0
        for tid, ps, cs, _ in self.tensor_views:
            size = self.tensors[tid]["size"]
            for p in ps:
                for c in cs:
                    total += size
                    if core[p] == core[c]:
                        internal += size
        return {"eligible_edge_bytes": total, "internalized_bytes": internal,
                "locality_ratio": internal / total if total else 1.0}

    def view(self, plan):
        mapping = {int(o): s for o, s in plan["node_to_subgraph"].items()}
        assignment = {s: c for c, seq in enumerate(plan["core_schedules"]) for s in seq}
        groups = defaultdict(list)
        for o, s in mapping.items():
            groups[s].append(o)
        return mapping, assignment, groups

    def reorder(self, plan, mode="rank"):
        """Global topological order projected to cores; keeps SG DAG acyclic."""
        mapping, assignment, groups = self.view(plan)
        sp, ss = {s: set() for s in groups}, {s: set() for s in groups}
        for o, ns in self.succ.items():
            for v in ns:
                a, b = mapping[o], mapping[v]
                if a != b:
                    ss[a].add(b)
                    sp[b].add(a)
        degree = {s: len(ps) for s, ps in sp.items()}
        ready = [s for s in sorted(groups) if not degree[s]]
        topo = []
        while ready:
            s = heappop(ready)
            topo.append(s)
            for nxt in sorted(ss[s]):
                degree[nxt] -= 1
                if not degree[nxt]:
                    heappush(ready, nxt)
        if len(topo) != len(groups):
            raise ValueError("subgraph contraction introduces a dependency cycle")
        work = {s: max(sum(self.ops[o]["cycles"] for o in members
                           if self.ops[o]["pipe"] == p) for p in ("PIPE_M", "PIPE_V"))
                for s, members in groups.items()}
        rank = {}
        for s in reversed(topo):
            rank[s] = work[s] + max((rank[t] for t in ss[s]), default=0)
        # Static release benefit only ranks ready SGs; it is not a memory proof.
        release = dict.fromkeys(groups, 0)
        for tid, ps, cs, _ in self.tensor_views:
            src = {mapping[o] for o in ps}
            dst = {mapping[o] for o in cs}
            for s in dst:
                release[s] += self.tensors[tid]["size"] / max(1, len(dst))
            for s in src:
                release[s] -= self.tensors[tid]["size"]
        key = lambda s: ((-release[s], -rank[s], s) if mode == "release" else
                         (min(self.depth[o] for o in groups[s]), s) if mode == "stable" else (-rank[s], s))
        ready = []
        degree = {s: len(ps) for s, ps in sp.items()}
        for s in groups:
            if not degree[s]:
                heappush(ready, (key(s), s))
        schedules = [[] for _ in range(self.n)]
        while ready:
            _, s = heappop(ready)
            schedules[assignment[s]].append(s)
            for nxt in sorted(ss[s]):
                degree[nxt] -= 1
                if not degree[nxt]:
                    heappush(ready, (key(nxt), nxt))
        return {"node_to_subgraph": dict(plan["node_to_subgraph"]), "core_schedules": schedules}

    def estimate(self, plan):
        mapping, assignment, groups = self.view(plan)
        core = {o: assignment[s] for o, s in mapping.items()}
        load = [[0, 0] for _ in range(self.n)]
        for o, op in self.ops.items():
            load[core[o]][op["pipe"] == "PIPE_V"] += op["cycles"]
        # Exactly follows original scene-B task construction before spill:
        # one input read per consumer core; TWO copies per source-target pair.
        transfer = 0
        for tid, ps, cs, output in self.tensor_views:
            a, b = {core[o] for o in ps}, {core[o] for o in cs}
            copies = (len(b) if cs and not ps else 0)
            copies += len(a) if ps and (output or not cs) else 0
            copies += 2 * sum(x != y for x in a for y in b)
            transfer += copies * self.tensors[tid]["size"]
        finish = {}
        for o in self.order:
            finish[o] = self.ops[o]["cycles"] + max((finish[p] + (
                self.delay + 2*self.edge_bytes[p, o]/self.bw if core[p] != core[o] else 0)
                for p in self.pred[o]), default=0)
        surrogate = max(max(map(max, load), default=0), max(finish.values(), default=0), transfer/self.bw)
        return surrogate, transfer, load

    def place_eft(self, plan):
        """Scene-B adapted earliest-finish construction on a fixed partition.

        Same-core links cost zero in this screening model. Separate M/V loads
        and per-core input reuse are included; exact overlap is simulated later.
        """
        mapping, _, groups = self.view(plan)
        pred, succ = {s: set() for s in groups}, {s: set() for s in groups}
        traffic, inputs = defaultdict(int), defaultdict(set)
        for tid, ps, cs, _ in self.tensor_views:
            a, b = {mapping[o] for o in ps}, {mapping[o] for o in cs}
            if not ps:
                for s in b:
                    inputs[s].add(tid)
            for x in a:
                for y in b-{x}:
                    pred[y].add(x)
                    succ[x].add(y)
                    traffic[x, y] += self.tensors[tid]["size"]
        # Use the certified global SG topological order, not min-node depth.
        degree = {s: len(pred[s]) for s in groups}
        ready, topo = sorted(s for s in groups if not degree[s]), []
        while ready:
            s = heappop(ready)
            topo.append(s)
            for nxt in sorted(succ[s]):
                degree[nxt] -= 1
                if not degree[nxt]:
                    heappush(ready, nxt)
        if len(topo) != len(groups):
            raise ValueError("cyclic subgraph graph")
        work = {s: [sum(self.ops[o]["cycles"] for o in members if self.ops[o]["pipe"] == p)
                    for p in ("PIPE_M", "PIPE_V")] for s, members in groups.items()}
        rank = {}
        for s in reversed(topo):
            rank[s] = max(work[s]) + max((rank[t]+self.delay+2*traffic[s,t]/self.bw
                                        for t in succ[s]), default=0)
        clocks, loaded = [[0., 0.] for _ in range(self.n)], [set() for _ in range(self.n)]
        placed, finish, schedules = {}, {}, [[] for _ in range(self.n)]
        degree = {s: len(pred[s]) for s in groups}
        ready = sorted((-rank[s], s) for s in groups if not degree[s])
        while ready:
            _, s = heappop(ready)
            def estimate_on(c):
                release = max((finish[p] + (self.delay+2*traffic[p,s]/self.bw
                                           if placed[p] != c else 0) for p in pred[s]), default=0.)
                release += sum(self.tensors[t]["size"] for t in inputs[s]-loaded[c])/self.bw
                ends = [max(clocks[c][p], release)+work[s][p] if work[s][p] else clocks[c][p]
                        for p in range(2)]
                return max(ends+[release]), ends
            c = min(range(self.n), key=lambda c: (estimate_on(c)[0], c))
            finish[s], clocks[c] = estimate_on(c)
            placed[s] = c
            loaded[c].update(inputs[s])
            schedules[c].append(s)
            for nxt in sorted(succ[s]):
                degree[nxt] -= 1
                if not degree[nxt]:
                    heappush(ready, (-rank[nxt], nxt))
        return {"node_to_subgraph": dict(plan["node_to_subgraph"]), "core_schedules": schedules}

    def construct(self, descriptor):
        family, width, active = descriptor
        if family == "base":
            plan = make_plan(self.graph, active)
        elif family == "valley":
            plan = valley_stage_plan(self.graph, active, split_shared=True,
                                     narrow_rule="mode", min_band_depth=width)
        else:
            plan = depth_band_plan(self.graph, active, width=width,
                                   data_aware=family == "data")
        plan["core_schedules"].extend([] for _ in range(self.n-active))
        return plan

    def local_candidates(self, plan, limit):
        mapping, assignment, groups = self.view(plan)
        _, _, load = self.estimate(plan)
        heavy = sorted(groups, key=lambda s: (
            -max(load[assignment[s]]),
            -sum(self.ops[o]["cycles"] for o in groups[s]), s))[:limit]
        for s in heavy:
            for target in range(self.n):
                if target == assignment[s]:
                    continue
                p = {"node_to_subgraph": dict(plan["node_to_subgraph"]),
                     "core_schedules": [[v for v in seq if v != s] for seq in plan["core_schedules"]]}
                p["core_schedules"][target].append(s)
                yield f"move_s{s}_c{target}", self.reorder(p, "stable")
            # A topological half split targets a heavy SG without cutting all SGs.
            levels = sorted({self.depth[o] for o in groups[s]})
            if len(levels) < 2:
                continue
            cut = levels[(len(levels)-1)//2]
            moved = [o for o in groups[s] if self.depth[o] > cut]
            new_s = max(groups)+1
            targets = sorted(range(self.n), key=lambda c: (max(load[c]), c))[:2]
            for target in targets:
                p = {"node_to_subgraph": dict(plan["node_to_subgraph"]),
                     "core_schedules": [list(seq) for seq in plan["core_schedules"]]}
                for o in moved:
                    p["node_to_subgraph"][str(o)] = new_s
                p["core_schedules"][target].append(new_s)
                yield f"split_s{s}_d{cut}_c{target}", self.reorder(p)
            # Preserve independent components: splitting all components in a SG
            # together can create needless communications on unrelated chains.
            pieces = defaultdict(list)
            for o in groups[s]:
                pieces[self.component[o]].append(o)
            pieces = sorted(pieces.items(), key=lambda item:
                            (-sum(self.ops[o]["cycles"] for o in item[1]), item[0]))[:2]
            for root, members in pieces:
                ds = sorted({self.depth[o] for o in members})
                if len(ds) < 2:
                    continue
                cuts = {ds[min(len(ds)-2, int(q*len(ds)))] for q in (0.25, 0.5, 0.75)}
                for d in sorted(cuts):
                    moved = [o for o in members if self.depth[o] > d]
                    for target in targets:
                        if target == assignment[s]:
                            continue
                        p = {"node_to_subgraph": dict(plan["node_to_subgraph"]),
                             "core_schedules": [list(seq) for seq in plan["core_schedules"]]}
                        for o in moved:
                            p["node_to_subgraph"][str(o)] = new_s
                        p["core_schedules"][target].append(new_s)
                        yield f"chain_s{s}_r{root}_d{d}_c{target}", self.reorder(p, "stable")
        yield "release_order", self.reorder(plan, "release")
        yield "critical_order", self.reorder(plan, "rank")
        yield "eft_placement", self.place_eft(plan)


def solve(graph, cores, official, fixed_config, search, output, trace_dir):
    start = time.perf_counter()
    sys.path.insert(0, str(official))
    from evaluation_validation import read_evaluation_config, validate_graph
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config
    from stub_multicore_cut_and_schedule import derive_multicore_plan
    validate_graph(graph)
    settings = read_evaluation_config(str(fixed_config))
    delay = read_scene_b_config(str(fixed_config))["cross_core_copy_delay_cycles"]
    problem = Problem(graph, cores, settings["bandwidth"], delay, settings["capacity"])
    trace_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    seen, described, pending, elite, history = set(), set(), {}, [], []
    best, best_result, best_key = None, None, (float("inf"), float("inf"))
    calls, duplicate_count, invalid_count, pruned_count = 0, 0, 0, 0
    best_name = None

    def offer(name, plan, family, descriptor=None):
        nonlocal duplicate_count, invalid_count
        fp = fingerprint(plan)
        if fp in seen or fp in pending:
            duplicate_count += 1
            return
        try:
            derive_multicore_plan(graph, plan)
            estimate, traffic, load = problem.estimate(plan)
        except (ValueError, RuntimeError) as exc:
            invalid_count += 1
            history.append({"event": "invalid_structure", "name": name, "reason": str(exc),
                            "elapsed_s": time.perf_counter()-start})
            seen.add(fp)
            return
        loc = problem.locality_profile(plan)
        target = float(search.get("locality_target", 0.85))
        pending[fp] = dict(name=name, plan=plan, family=family, descriptor=descriptor,
                           proxy_cycles=estimate, pre_spill_bytes=traffic, fingerprint=fp,
                           locality_ratio=loc["locality_ratio"], internalized_bytes=loc["internalized_bytes"],
                           locality_deficit=max(0.0, target-loc["locality_ratio"]),
                           lower_bound_cycles=max(problem.compute_path_bound, max(map(max, load)), traffic/problem.bw))

    def describe(descriptor):
        if descriptor in described:
            return
        described.add(descriptor)
        offer("%s_w%d_k%d" % descriptor, problem.construct(descriptor), "structure", descriptor)

    def evaluate(candidate):
        nonlocal calls, best, best_result, best_key, best_name, invalid_count
        fp = candidate["fingerprint"]
        pending.pop(fp, None)
        seen.add(fp)
        calls += 1
        tick = time.perf_counter()
        row = {k: v for k, v in candidate.items() if k != "plan"}
        row.update(event="evaluation", evaluation=calls, status="ok", accepted=False)
        try:
            result = evaluate_scene_b(graph, candidate["plan"], bandwidth=settings["bandwidth"],
                                      capacity=settings["capacity"], cross_core_copy_delay=delay)
            movement = result["data_movement_bytes"]
            actual_pre_spill = movement["scheduled_copy_bytes"]-movement["spill_added_copy_bytes"]
            if actual_pre_spill != candidate["pre_spill_bytes"]:
                raise AssertionError("pre-spill tensor accounting differs from official evaluator")
            key = (result["makespan"], movement["added_copy_bytes"])
            peak_l1=max((p["L1"] for p in result["memory_peak_by_core"].values()), default=0)
            peak_ub=max((p["UB"] for p in result["memory_peak_by_core"].values()), default=0)
            row.update(makespan_cycles=key[0], added_copy_bytes=key[1],
                       spill_bytes=movement["spill_added_copy_bytes"],
                       peak_l1_bytes=peak_l1, peak_ub_bytes=peak_ub,
                       locality_ratio=candidate["locality_ratio"],
                       internalized_bytes=candidate["internalized_bytes"],
                       buffer85_ok=(peak_l1 <= 0.85*settings["capacity"]["L1"] and
                                    peak_ub <= 0.85*settings["capacity"]["UB"]))
            if any(p[pos] > settings["capacity"][pos] for p in result["memory_peak_by_core"].values()
                   for pos in ("L1", "UB")):
                raise AssertionError("official capacity invariant violated")
            if key < best_key:
                best, best_result, best_key, best_name = candidate["plan"], result, key, candidate["name"]
                row["accepted"] = True
                output.write_text(json.dumps(best, separators=(",", ":"))+"\n", encoding="utf-8")
            if candidate["descriptor"]:
                elite.append((key, candidate["descriptor"]))
        except (ValueError, RuntimeError) as exc:
            row.update(status="infeasible", reason=str(exc))
            invalid_count += 1
        row.update(evaluation_s=time.perf_counter()-tick, elapsed_s=time.perf_counter()-start,
                   best_cycles=best_key[0] if best else None,
                   best_added_bytes=best_key[1] if best else None)
        history.append(row)
        with (trace_dir/"search.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+"\n")
        return row

    # Fresh run always truncates old logs; there is deliberately no resume mode.
    (trace_dir/"search.jsonl").write_text("", encoding="utf-8")
    seeds = [("base", 0, cores), ("valley", 1, cores),
             ("valley", search["coarse_valley_depth"], cores),
             ("band", problem.initial_width, cores)]
    for d in seeds:
        if calls >= search["max_evaluations"] or (best and time.perf_counter()-start >= search["max_seconds"]):
            break
        describe(d)
        # A duplicate seed is not evaluated a second time.
        match = next((c for c in pending.values() if c["descriptor"] == d), None)
        if match:
            evaluate(match)
    expanded, local_parent = set(), None
    while calls < search["max_evaluations"] and time.perf_counter()-start < search["max_seconds"]:
        for _, d in sorted(elite)[:search["elite_structures"]]:
            if d in expanded:
                continue
            expanded.add(d)
            family, width, active = d
            for k in sorted({max(1, active-1), min(cores, active+1)} - {active}):
                describe((family, width, k))
            if family != "base":
                for w in sorted({max(1, width//2), min(search["max_band_depth"], width*2)} - {width}):
                    describe((family, w, active))
                if family in ("band", "data"):
                    describe(("data" if family == "band" else "band", width, active))
        if best is not None and fingerprint(best) != local_parent:
            local_parent = fingerprint(best)
            pending = {fp: c for fp, c in pending.items() if c["family"] != "local"}
            for name, plan in problem.local_candidates(best, search["heavy_groups"]):
                offer(name, plan, "local")
        # Only rigorous lower bounds may exclude a candidate without simulation.
        # Memory proxies and the communication critical-path proxy may not.
        for fp, c in list(pending.items()):
            if c["lower_bound_cycles"] > best_key[0]:
                history.append({"event": "bound_pruned", "name": c["name"],
                                "lower_bound_cycles": c["lower_bound_cycles"],
                                "incumbent_cycles": best_key[0]})
                seen.add(fp)
                del pending[fp]
                pruned_count += 1
        if not pending:
            break
        # Alternate structural exploration and improving the current placement.
        family = "local" if calls % 2 else "structure"
        choices = [c for c in pending.values() if c["family"] == family] or list(pending.values())
        selected = min(choices, key=lambda c: (c["locality_deficit"], c["proxy_cycles"],
                                               c["pre_spill_bytes"], -c["internalized_bytes"],
                                               c["name"], c["fingerprint"]))
        evaluate(selected)
    if best is None:
        raise RuntimeError("No officially feasible candidate within the configured budget")
    with gzip.open(trace_dir/"official_result.json.gz", "wt", encoding="utf-8", compresslevel=1) as stream:
        json.dump(best_result, stream, separators=(",", ":"))
    initial = next(r for r in history if r.get("status") == "ok")
    report = dict(schema=VERSION, cold_start=True, graph_sha256=hashlib.sha256(
        json.dumps(graph, sort_keys=True).encode()).hexdigest(),
        config_sha256=hashlib.sha256(fixed_config.read_bytes()).hexdigest(), search_config=search,
        cores=cores, initial_cycles=initial["makespan_cycles"], makespan_cycles=best_key[0],
        added_copy_bytes=best_key[1], evaluations=calls, elapsed_s=time.perf_counter()-start,
        invalid_candidates=invalid_count, duplicates_skipped=duplicate_count, bound_pruned=pruned_count, selected=best_name,
        selected_fingerprint=fingerprint(best), initial_width=problem.initial_width,
        stop_reason="evaluation_budget" if calls >= search["max_evaluations"] else
                    "time_budget" if time.perf_counter()-start >= search["max_seconds"] else "no_new_candidate",
        time_budget_semantics="Stop before the next evaluation; an in-flight official evaluation completes.",
        io_contract="input graph + official code/config + fixed search parameters; no saved plans read")
    (trace_dir/"run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (trace_dir/"events.json").write_text(json.dumps(history, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("-n", "--num-cores", type=int, required=True, choices=range(2, 6))
    parser.add_argument("--official-code", type=Path, default=Path(__file__).resolve().parents[3]/"official"/"code")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--search-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--trace-dir", type=Path)
    args = parser.parse_args()
    target = args.output or args.graph.with_name(args.graph.stem+"_multicore_res.json")
    trace = args.trace_dir or target.with_suffix("").with_name(target.stem+"_search")
    report = solve(json.loads(args.graph.read_text(encoding="utf-8")), args.num_cores,
                   args.official_code, args.config or args.graph.with_name("config.txt"),
                   json.loads(args.search_config.read_text(encoding="utf-8")), target, trace)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
