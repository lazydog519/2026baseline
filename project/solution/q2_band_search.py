"""Scene-B search over depth-band size and active-core count.

Band width controls the lifetime of same-core resident tensors; active-core
count trades parallel work against repeated DDR reads.  Both are merely plan
parameters: only the original Problem 2 evaluator decides feasibility/score.
"""

import argparse
import csv
import gzip
import json
import sys
import time
import traceback
from pathlib import Path

from baseline import make_plan
from q1_optimized import active_core_plan, depth_band_plan


FIELDS = ("case", "cores", "strategy", "active_cores", "band_width",
          "data_aware", "status", "makespan_cycles", "added_copy_bytes",
          "partition_added_copy_bytes", "spill_added_copy_bytes",
          "peak_l1_bytes", "peak_ub_bytes", "wall_seconds", "error")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", type=int, required=True)
    parser.add_argument("--cores", nargs="+", type=int, default=[5])
    parser.add_argument("--widths", nargs="+", type=int, default=[4, 8, 12])
    parser.add_argument("--data-aware", action="store_true")
    args = parser.parse_args()
    project = args.project.resolve()
    sys.path.insert(0, str(project / "official" / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config

    config = project / "official" / "data" / "config.txt"
    settings = read_evaluation_config(str(config))
    scene = read_scene_b_config(str(config))
    root = project / "q2_optimization" / ("data_band" if args.data_aware else "band")
    root.mkdir(parents=True, exist_ok=True)
    summary = root / "candidate_summary.csv"
    done = set()
    if summary.exists():
        with summary.open(encoding="utf-8", newline="") as stream:
            done = {(r["case"], int(r["cores"]), r["strategy"])
                    for r in csv.DictReader(stream)
                    if r["status"] in ("ok", "duplicate")}
    with summary.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if stream.tell() == 0:
            writer.writeheader()
        for index in args.cases:
            case = f"case_{index:03d}"
            graph = json.loads((project / "official" / "data" / f"{case}.json")
                               .read_text(encoding="utf-8"))
            for cores in args.cores:
                selected = json.loads((project / "q1_optimization" / "final" /
                                       "plans" / f"n{cores}" /
                                       f"{case}_multicore_res.json")
                                      .read_text(encoding="utf-8"))
                seen = {json.dumps(make_plan(graph, cores), sort_keys=True),
                        json.dumps(selected, sort_keys=True)}
                for active in range(2, cores + 1):
                    for width in args.widths:
                        strategy = f"{'data_' if args.data_aware else ''}band_w{width}_k{active}"
                        if (case, cores, strategy) in done:
                            continue
                        row = dict.fromkeys(FIELDS, "")
                        row.update(case=case, cores=cores, strategy=strategy,
                                   active_cores=active, band_width=width,
                                   data_aware=int(args.data_aware))
                        start = time.perf_counter()
                        try:
                            plan = active_core_plan(
                                lambda g, n: depth_band_plan(
                                    g, n, width, data_aware=args.data_aware),
                                graph, cores, active)
                            fingerprint = json.dumps(plan, sort_keys=True)
                            if fingerprint in seen:
                                row["status"] = "duplicate"
                                continue
                            seen.add(fingerprint)
                            folder = root / case / f"n{cores}" / strategy
                            folder.mkdir(parents=True, exist_ok=True)
                            (folder / f"{case}_multicore_res.json").write_text(
                                json.dumps(plan, separators=(",", ":")) + "\n",
                                encoding="utf-8")
                            result = evaluate_scene_b(
                                graph, plan, bandwidth=settings["bandwidth"],
                                capacity=settings["capacity"],
                                cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
                            movement = result["data_movement_bytes"]
                            peaks = result["memory_peak_by_core"].values()
                            row.update(
                                status="ok", makespan_cycles=result["makespan"],
                                added_copy_bytes=movement["added_copy_bytes"],
                                partition_added_copy_bytes=movement["partition_added_copy_bytes"],
                                spill_added_copy_bytes=movement["spill_added_copy_bytes"],
                                peak_l1_bytes=max((p["L1"] for p in peaks), default=0),
                                peak_ub_bytes=max((p["UB"] for p in result["memory_peak_by_core"].values()), default=0))
                            with gzip.open(folder / "result.json.gz", "wt",
                                           encoding="utf-8", compresslevel=1) as output:
                                json.dump(result, output, ensure_ascii=False,
                                          separators=(",", ":"))
                        except Exception:
                            row.update(status="error", error=traceback.format_exc()[-1600:])
                            folder = root / case / f"n{cores}" / strategy
                            folder.mkdir(parents=True, exist_ok=True)
                            (folder / "error.txt").write_text(row["error"], encoding="utf-8")
                        finally:
                            row["wall_seconds"] = round(time.perf_counter() - start, 3)
                            writer.writerow(row)
                            stream.flush()
                            print(case, cores, strategy, row["status"],
                                  row["makespan_cycles"], row["wall_seconds"], flush=True)


if __name__ == "__main__":
    main()
