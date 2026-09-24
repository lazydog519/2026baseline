"""Evaluate Problem 1 partition candidates with the untouched official evaluator."""

import argparse
import csv
import gzip
import json
import sys
import time
import traceback
from functools import partial
from pathlib import Path

from baseline import make_plan as baseline_plan
from q1_optimized import (active_core_plan, depth_band_plan, first_join_plan,
                          heft_task_schedule,
                          mask_band_plan,
                          fork_join_plan, terminal_branch_plan, valley_stage_plan)


def limited(make, active):
    return lambda graph, available: (active_core_plan(make, graph, available, active)
                                     if active <= available else baseline_plan(graph, available))


def with_heft(make, cross_wait=1000, same_wait=100, bandwidth=60):
    return lambda graph, cores: heft_task_schedule(
        graph, make(graph, cores), cores, cross_wait=cross_wait,
        same_wait=same_wait, bandwidth=bandwidth)


STRATEGIES = {"first_join": first_join_plan,
              **{f"baseline_k{k}": limited(baseline_plan, k)
                 for k in (2, 3, 4)},
              "terminal_branch": terminal_branch_plan,
              "fork_join": fork_join_plan,
              "valley_stage": valley_stage_plan,
              "valley_split": partial(valley_stage_plan, split_shared=True),
              "valley_mode": partial(valley_stage_plan, split_shared=True,
                                     narrow_rule="mode"),
              "mask_global": mask_band_plan,
              "source_global": partial(mask_band_plan, direction="sources"),
              **{f"source_band_{width}": partial(mask_band_plan,
                                                  width=width,
                                                  direction="sources")
                 for width in (8, 16, 32, 64)},
              **{f"source_stage_{width}": partial(mask_band_plan,
                                                   width=width,
                                                   reset_load=True,
                                                   direction="sources")
                 for width in (8, 16, 32, 64)},
              "band_12_heft": with_heft(partial(depth_band_plan, width=12)),
              "band_16_heft": with_heft(partial(depth_band_plan, width=16)),
              **{f"data_band_{width}": partial(depth_band_plan, width=width,
                                                data_aware=True)
                 for width in (8, 12, 16, 24, 32)},
              **{f"data_band_{width}_heft": with_heft(partial(
                  depth_band_plan, width=width, data_aware=True))
                 for width in (8, 12, 16, 24, 32)},
              "fork_join_heft": with_heft(fork_join_plan),
              "fork_join_k4_heft": with_heft(limited(fork_join_plan, 4)),
              "terminal_branch_heft": with_heft(terminal_branch_plan),
              "first_join_heft": with_heft(first_join_plan),
              "mask_stage_16_heft": with_heft(partial(mask_band_plan, width=16,
                                                       reset_load=True)),
              "valley_mode_heft": with_heft(partial(valley_stage_plan,
                                                     split_shared=True,
                                                     narrow_rule="mode")),
              **{f"valley_merge_{depth}": partial(valley_stage_plan,
                                                   split_shared=True,
                                                   narrow_rule="mode",
                                                   min_band_depth=depth)
                 for depth in (4, 6, 8, 10, 12, 14, 16, 20, 24, 32, 40, 48, 64)},
              **{f"valley_merge_{depth}_heft": with_heft(partial(
                  valley_stage_plan, split_shared=True, narrow_rule="mode",
                  min_band_depth=depth)) for depth in
                 (4, 6, 8, 10, 12, 14, 16, 20, 24, 32, 40, 48, 64)},
              **{f"mask_band_{width}": partial(mask_band_plan, width=width)
                 for width in (4, 8, 12, 16, 24, 32, 48, 64)},
              **{f"mask_stage_{width}": partial(mask_band_plan, width=width,
                                                 reset_load=True)
                 for width in (16, 32, 64)},
              **{f"valley_stage_k{k}": limited(valley_stage_plan, k)
                 for k in (2, 3, 4)},
              **{f"fork_join_k{k}": limited(fork_join_plan, k) for k in (2, 3, 4)},
              **{f"terminal_branch_k{k}": limited(terminal_branch_plan, k)
                 for k in (2, 3, 4)},
              **{f"band_{width}": partial(depth_band_plan, width=width)
                 for width in (2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 128)}}
FIELDS = ("case", "cores", "strategy", "status", "makespan_cycles",
          "added_copy_bytes", "scheduled_copy_bytes", "subgraphs",
          "wall_seconds", "error")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--search-config", type=Path,
                        default=Path(__file__).resolve().parent.parent /
                        "q1_optimization" / "search_config.json")
    parser.add_argument("--cases", nargs="+", type=int, required=True)
    parser.add_argument("--cores", nargs="+", type=int, default=[5])
    parser.add_argument("--strategies", nargs="+",
                        default=list(STRATEGIES))
    args = parser.parse_args()
    sys.path.insert(0, str(args.official / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_1 import evaluate_scene_a, read_scene_a_config

    config = args.official / "data" / "config.txt"
    settings = read_evaluation_config(str(config))
    scene = read_scene_a_config(str(config))
    search_config = json.loads(args.search_config.read_text(encoding="utf-8"))
    delta = (scene["task_cross_core_wait_cycles"]
             - scene["task_same_core_wait_cycles"])
    strategies = dict(STRATEGIES)
    for fraction in search_config["affinity_wait_fractions"]:
        name = f"valley_split_aff{round(100 * fraction):03d}"
        strategies[name] = partial(valley_stage_plan, split_shared=True,
                                   affinity_cycles=delta * fraction)
    for name in tuple(strategies):
        if name.endswith("_heft"):
            strategies[name] = with_heft(
                strategies[name.removesuffix("_heft")],
                cross_wait=scene["task_cross_core_wait_cycles"],
                same_wait=scene["task_same_core_wait_cycles"],
                bandwidth=settings["bandwidth"])
    unknown = set(args.strategies) - strategies.keys()
    if unknown:
        parser.error(f"unknown strategies: {sorted(unknown)}")
    args.output.mkdir(parents=True, exist_ok=True)
    summary = args.output / "candidate_summary.csv"
    done = set()
    if summary.exists():
        with summary.open(encoding="utf-8", newline="") as fp:
            done = {(r["case"], int(r["cores"]), r["strategy"])
                    for r in csv.DictReader(fp) if r["status"] == "ok"}
    with summary.open("a", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        if fp.tell() == 0:
            writer.writeheader()
        for case in args.cases:
            name = f"case_{case:03d}"
            graph = json.loads((args.official / "data" / f"{name}.json")
                               .read_text(encoding="utf-8"))
            for cores in args.cores:
                reference = baseline_plan(graph, cores)
                for strategy in args.strategies:
                    if (name, cores, strategy) in done:
                        continue
                    plan = strategies[strategy](graph, cores)
                    if plan == reference:
                        continue
                    folder = args.output / name / f"n{cores}" / strategy
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / f"{name}_multicore_res.json").write_text(
                        json.dumps(plan, separators=(",", ":")) + "\n",
                        encoding="utf-8")
                    row = dict.fromkeys(FIELDS, "")
                    row.update(case=name, cores=cores, strategy=strategy,
                               subgraphs=len(set(plan["node_to_subgraph"].values())))
                    t0 = time.perf_counter()
                    try:
                        result = evaluate_scene_a(
                            graph, plan, bandwidth=settings["bandwidth"],
                            capacity=settings["capacity"],
                            cross_core_wait=scene["task_cross_core_wait_cycles"],
                            same_core_wait=scene["task_same_core_wait_cycles"])
                        movement = result["data_movement_bytes"]
                        row.update(status="ok", makespan_cycles=result["makespan"],
                                   added_copy_bytes=movement["added_copy_bytes"],
                                   scheduled_copy_bytes=movement["scheduled_copy_bytes"])
                        with gzip.open(folder / "result.json.gz", "wt",
                                       encoding="utf-8", compresslevel=1) as out:
                            json.dump(result, out, ensure_ascii=False,
                                      separators=(",", ":"))
                    except Exception:
                        row.update(status="error", error=traceback.format_exc()[-1500:])
                        (folder / "error.txt").write_text(row["error"], encoding="utf-8")
                    row["wall_seconds"] = round(time.perf_counter() - t0, 3)
                    writer.writerow(row)
                    fp.flush()
                    print(name, cores, strategy, row["status"],
                          row["makespan_cycles"], row["wall_seconds"], flush=True)


if __name__ == "__main__":
    main()
