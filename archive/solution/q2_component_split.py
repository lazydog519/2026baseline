"""Split one heavy compute component at a topological cut, then score in B.

This is a local alternative to cutting every component into depth bands.  The
original graph, official evaluator, and config are never modified.
"""

import argparse
import csv
import gzip
import json
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

from baseline import make_plan
from q1_optimized import compute_dag, topological_depth


FIELDS = ("case", "cores", "strategy", "component_rank", "cut_level",
          "source_core", "target_core", "status", "makespan_cycles",
          "added_copy_bytes", "spill_added_copy_bytes", "peak_l1_bytes",
          "peak_ub_bytes", "wall_seconds", "error")


def components(graph):
    ops, _, succ = compute_dag(graph)
    parent = {oid: oid for oid in ops}

    def find(oid):
        while parent[oid] != oid:
            parent[oid] = parent[parent[oid]]
            oid = parent[oid]
        return oid

    for oid in ops:
        for nxt in succ[oid]:
            a, b = find(oid), find(nxt)
            if a != b:
                parent[max(a, b)] = min(a, b)
    groups = defaultdict(list)
    for oid in ops:
        groups[find(oid)].append(oid)
    return sorted(groups.values(), key=lambda ids: (
        -max(sum(ops[o]["cycles"] for o in ids if ops[o]["pipe"] == pipe)
             for pipe in ("PIPE_M", "PIPE_V")), min(ids)))


def split_plan(base, moved, target):
    plan = {"node_to_subgraph": dict(base["node_to_subgraph"]),
            "core_schedules": [list(s) for s in base["core_schedules"]]}
    new_id = max(plan["node_to_subgraph"].values(), default=-1) + 1
    for oid in moved:
        plan["node_to_subgraph"][str(oid)] = new_id
    plan["core_schedules"][target].append(new_id)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", type=int, required=True)
    parser.add_argument("--cores", type=int, default=5)
    parser.add_argument("--max-components", type=int, default=2)
    args = parser.parse_args()
    project = args.project.resolve()
    sys.path.insert(0, str(project / "official" / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config

    config = project / "official" / "data" / "config.txt"
    settings = read_evaluation_config(str(config))
    scene = read_scene_b_config(str(config))
    root = project / "q2_optimization" / "component_split"
    root.mkdir(parents=True, exist_ok=True)
    summary = root / "candidate_summary.csv"
    done = set()
    if summary.exists():
        with summary.open(encoding="utf-8", newline="") as stream:
            done = {(r["case"], int(r["cores"]), r["strategy"])
                    for r in csv.DictReader(stream) if r["status"] == "ok"}
    with summary.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if stream.tell() == 0:
            writer.writeheader()
        for index in args.cases:
            case = f"case_{index:03d}"
            graph = json.loads((project / "official" / "data" / f"{case}.json")
                               .read_text(encoding="utf-8"))
            base = make_plan(graph, args.cores)
            ops, pred, succ = compute_dag(graph)
            _, depth = topological_depth(ops, pred, succ)
            for rank, members in enumerate(components(graph)[:args.max_components]):
                source = base["node_to_subgraph"][str(members[0])]
                levels = sorted({depth[oid] for oid in members})
                if len(levels) < 2:
                    continue
                cuts = sorted({levels[min(len(levels) - 2, int(f * len(levels)))]
                               for f in (0.25, 0.4, 0.5, 0.6, 0.75)})
                for cut in cuts:
                    moved = [oid for oid in members if depth[oid] > cut]
                    if not moved or len(moved) == len(members):
                        continue
                    for target in range(args.cores):
                        if target == source:
                            continue
                        strategy = f"component{rank}_cut{cut}_to{target}"
                        if (case, args.cores, strategy) in done:
                            continue
                        plan = split_plan(base, moved, target)
                        folder = root / case / f"n{args.cores}" / strategy
                        folder.mkdir(parents=True, exist_ok=True)
                        (folder / f"{case}_multicore_res.json").write_text(
                            json.dumps(plan, separators=(",", ":")) + "\n",
                            encoding="utf-8")
                        row = dict.fromkeys(FIELDS, "")
                        row.update(case=case, cores=args.cores, strategy=strategy,
                                   component_rank=rank, cut_level=cut,
                                   source_core=source, target_core=target)
                        start = time.perf_counter()
                        try:
                            result = evaluate_scene_b(
                                graph, plan, bandwidth=settings["bandwidth"],
                                capacity=settings["capacity"],
                                cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
                            movement = result["data_movement_bytes"]
                            peaks = result["memory_peak_by_core"].values()
                            row.update(
                                status="ok", makespan_cycles=result["makespan"],
                                added_copy_bytes=movement["added_copy_bytes"],
                                spill_added_copy_bytes=movement["spill_added_copy_bytes"],
                                peak_l1_bytes=max((p["L1"] for p in peaks), default=0),
                                peak_ub_bytes=max((p["UB"] for p in result["memory_peak_by_core"].values()), default=0))
                            with gzip.open(folder / "result.json.gz", "wt",
                                           encoding="utf-8", compresslevel=1) as output:
                                json.dump(result, output, ensure_ascii=False,
                                          separators=(",", ":"))
                        except Exception:
                            row.update(status="error", error=traceback.format_exc()[-1600:])
                            (folder / "error.txt").write_text(row["error"], encoding="utf-8")
                        row["wall_seconds"] = round(time.perf_counter() - start, 3)
                        writer.writerow(row)
                        stream.flush()
                        print(case, args.cores, strategy, row["status"],
                              row["makespan_cycles"], row["wall_seconds"], flush=True)


if __name__ == "__main__":
    main()
