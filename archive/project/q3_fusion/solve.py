"""Cold-start, event-guided U-NSGA-III for the official Problem 3 evaluator.

The old solver supplies unchanged initialization, objective evaluation, and
reference-direction survival. Only the *proposal* mechanism is replaced here.
No historical plan, simulator patch, artificial wait, or cache-state preload.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT / "q3_nsga"))
import solve as original


class GuidedModel(original.Model):
    def __init__(self, graph, n, config):
        super().__init__(graph, n, config)
        # Compute-only lower bound: neither DDR nor cache benefit can make a
        # compute pipe execute more than one op per core and cycle.
        longest = {}
        work = [0, 0]
        for v in self.topo:
            op = self.ops[v]
            j = 0 if op["pipe"] == "PIPE_M" else 1
            work[j] += op["cycles"]
            longest[v] = op["cycles"] + max((longest[u] for u in self.pred[v]), default=0)
        self.compute_lb = max(max(longest.values()), max(work) / n)

    def propose(self, parent, donor, rng, engineering, bw, cross=False):
        if not engineering:
            return super().propose(parent, donor, rng, False, bw, cross)
        groups, cores = self.parts(parent["plan"])
        priority = {s: float(i) for seq in parent["plan"]["core_schedules"]
                    for i, s in enumerate(seq)}
        _, order = self.repair(groups, cores, priority)
        priority = {s: float(i) for i, s in enumerate(order)}
        crossed = False
        if cross:
            donor_groups, donor_cores = self.parts(donor["plan"])
            donor_core = {v: donor_cores[s] for s, vs in donor_groups.items()
                          for v in vs}
            for s in sorted(groups):
                if rng.random() < 0.5:
                    counts = Counter(donor_core[v] for v in groups[s])
                    cores[s] = min(counts, key=lambda c: (-counts[c], c))
                    crossed = True
        result = parent["result"]
        timeline = result["per_core_timeline"]
        finish = {c["core_id"]: max((o["end"] for o in c["ops"]), default=0)
                  for c in timeline}
        critical = max(finish, key=lambda k: (finish[k], -k))
        work = self.work(groups)
        load = np.zeros((self.n, 2))
        for s, w in work.items():
            load[cores[s]] += w
        tails = defaultdict(int)
        op_info = {}
        tensor_users = defaultdict(set)
        threshold = 0.75 * result["makespan"]
        for c in timeline:
            for o in c["ops"]:
                op_info[(c["core_id"], o["op_id"])] = o
                if o.get("cache_tensor_id") is not None:
                    tensor_users[o["cache_tensor_id"]].add(
                        (o["subgraph_id"], c["core_id"]))
                if o["end"] >= threshold and o["op"] not in ("COPY_IN", "COPY_OUT"):
                    tails[o["subgraph_id"]] += o["duration"]
        # FIFO events distinguish a miss before the first fill from a
        # capacity miss after a prior insertion. Hits never refresh FIFO.
        miss = defaultdict(int)
        repeated = defaultdict(list)
        inserted = set()
        for event in result["cache_events"]:
            if event["event"] == "insert":
                inserted.add(event["tensor_id"])
            elif event["event"] == "miss":
                o = op_info.get((event["core_id"], event["op_id"]))
                if o is not None:
                    s = o["subgraph_id"]
                    miss[s] += event["size_bytes"]
                    if event["tensor_id"] in inserted:
                        repeated[event["tensor_id"]].append((s, event["core_id"], event["size_bytes"]))

        # The lower bound guides the neighborhood, never the final score.
        gap = result["makespan"] / self.compute_lb
        can_split = self.n > 1 and len(groups) < self.cfg["max_subgraphs"]
        largest = max((max(work[s]) for s in groups if cores[s] == critical), default=0)
        imbalance = max(load[critical]) / max(1.0, np.max(np.mean(load, axis=0)))
        if self.n == 1:
            modes = ["order", "merge"]
        elif gap > 1.35 and can_split and largest > 0.25 * max(load[critical]):
            modes = ["split", "split", "move", "affinity", "order"]
        elif imbalance > 1.12:
            modes = ["move", "move", "split", "affinity", "order"]
        else:
            modes = ["affinity", "order", "move", "merge"]
        mode = modes[int(rng.integers(len(modes)))]
        meta = dict(operator=mode, gap_to_compute_lb=round(gap, 4),
                    critical_core=critical, tail_threshold=threshold)
        if crossed:
            meta["crossover"] = "whole_subgraph_donor_majority"

        if mode == "split":
            choices = [s for s in groups if cores[s] == critical and len(groups[s]) >= 4]
            if not choices or not can_split:
                mode = "move"
            else:
                choices.sort(key=lambda s: (-max(work[s]), -tails[s], s))
                s = choices[min(int(rng.integers(3)), len(choices) - 1)]
                vs = groups[s]
                weights = [self.ops[v]["cycles"] for v in vs]
                total = sum(weights)
                cuts = []
                for ratio in (0.30, 0.45, 0.55, 0.70):
                    limit = total * ratio
                    cumulative = 0
                    for i, w in enumerate(weights, start=1):
                        cumulative += w
                        if cumulative >= limit:
                            if i < len(vs):
                                cuts.append(i)
                            break
                cuts = sorted(set(cuts))
                def cutbytes(k):
                    left, right = set(vs[:k]), set(vs[k:])
                    return (sum(size for size, prod, cons in self.tensors
                                if prod & left and cons & right)
                            + sum(b for u, v, b in self.direct if u in left and v in right))
                k = min(cuts, key=lambda i: (cutbytes(i) / max(1, total),
                                             abs(sum(weights[:i]) / total - 0.5), i))
                new = max(groups) + 1
                groups[s], groups[new] = vs[:k], vs[k:]
                cores[new] = cores[s]
                priority[new] = priority[s] + 0.1
                # Estimate candidate load and communication. This ranking
                # is only a proposal filter; the official simulator decides.
                trial_work = self.work(groups)[new]
                destinations = [c for c in range(self.n) if c != critical]
                destinations.sort(key=lambda c: (max(load[c] + trial_work), c))
                cores[new] = destinations[min(int(rng.integers(min(2, len(destinations)))),
                                               len(destinations) - 1)]
                meta.update(subgraph=s, new_subgraph=new, cut=k,
                            cut_proxy_bytes=cutbytes(k), target=cores[new])

        if mode == "move":
            choices = [s for s in groups if cores[s] == critical]
            choices.sort(key=lambda s: (-(max(work[s]) + 0.5 * tails[s]), s))
            if choices and self.n > 1:
                s = choices[min(int(rng.integers(min(4, len(choices)))), len(choices) - 1)]
                src = cores[s]
                destinations = [c for c in range(self.n) if c != src]
                destinations.sort(key=lambda c: (max(load[c] + work[s]), c))
                dst = destinations[min(int(rng.integers(min(2, len(destinations)))),
                                       len(destinations) - 1)]
                cores[s] = dst
                meta.update(subgraph=s, from_core=src, to_core=dst)

        if mode == "affinity":
            candidates = []
            # Only a *previously inserted* tensor gives a true FIFO
            # reaccess signal; first-fill races are not capacity misses.
            for tid, later in repeated.items():
                if not later:
                    continue
                for s, core, size in later:
                    if s not in groups:
                        continue
                    for other, target in tensor_users[tid]:
                        if other != s and target != core:
                            excess = max(load[target] + work[s])
                            candidates.append((size / max(1, excess), s, target, tid))
            if candidates:
                candidates.sort(reverse=True)
                _, s, target, tid = candidates[min(int(rng.integers(min(3, len(candidates)))),
                                                   len(candidates) - 1)]
                if cores[s] != target:
                    meta.update(subgraph=s, from_core=cores[s], to_core=target,
                                repeated_tensor=tid)
                    cores[s] = target
                else:
                    mode = "order"
            else:
                mode = "order"

        if mode == "order":
            choices = [s for s in groups if miss[s] and cores[s] == critical]
            if not choices:
                choices = [s for s in groups if miss[s]]
            if choices:
                choices.sort(key=lambda s: (-(miss[s] + tails[s]), s))
                s = choices[min(int(rng.integers(min(4, len(choices)))),
                                len(choices) - 1)]
                priority[s] = -1.0
                meta.update(prioritized_subgraph=s, observed_miss_bytes=miss[s])

        if mode == "merge":
            pairs = [(a, b) for a, b in zip(order, order[1:])
                     if cores[a] == cores[b]]
            if pairs:
                pairs.sort(key=lambda ab: (-(miss[ab[0]] + miss[ab[1]]), ab))
                a, b = pairs[min(int(rng.integers(min(3, len(pairs)))),
                                 len(pairs) - 1)]
                groups[a] = sorted(groups[a] + groups.pop(b), key=self.position.get)
                cores.pop(b)
                priority.pop(b)
                meta.update(merged=[a, b])

        plan, _ = self.repair(groups, cores, priority)
        meta["operator"] = mode
        return plan, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path)
    ap.add_argument("-n", type=int, choices=range(1, 6), required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--parameters", type=Path, default=HERE / "experiment.json")
    a = ap.parse_args()
    graph = json.loads(a.graph.read_text(encoding="utf-8"))
    cfg = json.loads(a.parameters.read_text(encoding="utf-8"))
    original.Model = GuidedModel
    summary = original.run(graph, a.n, a.graph.with_name("config.txt"), cfg,
                           "unsga3_npu", a.seed, a.output)
    summary["variant"] = "event_guided_unsga3"
    (a.output / "run.json").write_text(json.dumps(summary, indent=2) + "\n",
                                       encoding="utf-8")
    print(json.dumps({k: summary[k] for k in
                      ("makespan", "official_calls", "invalid_records", "variant")}),
          flush=True)


if __name__ == "__main__":
    main()
