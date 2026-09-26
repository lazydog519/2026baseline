"""Root-separator branch extraction added to event-guided U-NSGA-III.

This is a proposal operator, not a graph rewrite: every original operation is
kept once. The official evaluator expands COPYs, FIFO events and all capacity
constraints and alone determines feasibility and quality.
"""
import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
P = HERE.parent
spec = importlib.util.spec_from_file_location("guided_q3_solver", HERE / "solve.py")
guided = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guided)


class BranchModel(guided.GuidedModel):
    def branches(self, vertices):
        within = set(vertices)
        roots = {v for v in within if not (self.pred[v] & within)}
        if len(roots) < 2 or len(roots) > 64:
            return None
        remaining = within - roots
        parent = {v: v for v in remaining}

        def root(v):
            while parent[v] != v:
                parent[v] = parent[parent[v]]
                v = parent[v]
            return v

        for v in remaining:
            for u in self.succ[v] & remaining:
                a, b = root(v), root(u)
                if a != b:
                    parent[a] = b
        components = defaultdict(list)
        for v in remaining:
            components[root(v)].append(v)
        if len(components) < 2 or len(components) > 32:
            return None
        result = [sorted(roots, key=self.position.get)]
        result.extend(sorted((sorted(x, key=self.position.get)
                              for x in components.values()),
                             key=lambda x: min(self.position[v] for v in x)))
        return result

    def propose(self, parent, donor, rng, engineering, bw, cross=False):
        if not engineering or self.n == 1 or rng.random() >= 0.60:
            return super().propose(parent, donor, rng, engineering, bw, cross)
        groups, cores = self.parts(parent["plan"])
        work = self.work(groups)
        finish = {c["core_id"]: max((o["end"] for o in c["ops"]), default=0)
                  for c in parent["result"]["per_core_timeline"]}
        critical = max(finish, key=lambda k: (finish[k], -k))
        load = np.zeros((self.n, 2))
        for s, w in work.items():
            load[cores[s]] += w
        candidates = []
        for s, vs in groups.items():
            pieces = self.branches(vs)
            if pieces is None or len(groups) + len(pieces) - 1 > self.cfg["max_subgraphs"]:
                continue
            # Prefer a substantial parallel portion on a late core.
            tail_work = sum(self.ops[v]["cycles"] for part in pieces[1:] for v in part)
            score = tail_work * (1.5 if cores[s] == critical else 1.0)
            candidates.append((score, s, pieces))
        if not candidates:
            return super().propose(parent, donor, rng, True, bw, cross)
        candidates.sort(key=lambda x: (-x[0], x[1]))
        _, selected, pieces = candidates[min(int(rng.integers(min(3, len(candidates)))),
                                              len(candidates) - 1)]
        priority = {s: float(i) for seq in parent["plan"]["core_schedules"]
                    for i, s in enumerate(seq)}
        crossed = False
        if cross:
            other_groups, other_cores = self.parts(donor["plan"])
            donor_core = {v: other_cores[s] for s, vs in other_groups.items()
                          for v in vs}
            for s in sorted(groups):
                if rng.random() < 0.5:
                    counts = Counter(donor_core[v] for v in groups[s])
                    cores[s] = min(counts, key=lambda c: (-counts[c], c))
                    crossed = True
        source = cores[selected]
        load = np.zeros((self.n, 2))
        for s, w in work.items():
            if s != selected:
                load[cores[s]] += w
        groups[selected] = pieces[0]  # shared entry remains on its selected core
        root_work = self.work({selected: pieces[0]})[selected]
        load[source] += root_work
        assignments = []
        # Heavy branches first. They can run in parallel after the entry
        # dependencies; this never manufactures an explicit start time.
        ranked = sorted(pieces[1:],
                        key=lambda x: -max(self.work({0: x})[0]))
        for part in ranked:
            new = max(groups) + 1
            groups[new] = part
            w = self.work({new: part})[new]
            dest = min(range(self.n), key=lambda c: (max(load[c] + w), c))
            cores[new] = dest
            load[dest] += w
            priority[new] = priority[selected] + 0.001 * (len(assignments) + 1)
            assignments.append((new, dest, len(part)))
        plan, _ = self.repair(groups, cores, priority)
        return plan, dict(operator="root_separator_branch_split",
                          parent_subgraph=selected, entry_ops=len(pieces[0]),
                          independent_branches=len(pieces) - 1,
                          destinations=assignments,
                          crossover="whole_subgraph_donor_majority" if crossed else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path)
    ap.add_argument("-n", type=int, choices=range(1, 6), required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--parameters", type=Path, default=HERE / "branch_experiment.json")
    a = ap.parse_args()
    graph = json.loads(a.graph.read_text(encoding="utf-8"))
    cfg = json.loads(a.parameters.read_text(encoding="utf-8"))
    guided.original.Model = BranchModel
    summary = guided.original.run(
        graph, a.n, a.graph.with_name("config.txt"), cfg,
        "unsga3_npu", a.seed, a.output)
    summary["variant"] = "root_separator_unsga3"
    (a.output / "run.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in
                      ("makespan", "official_calls", "invalid_records", "variant")}),
          flush=True)


if __name__ == "__main__":
    main()
