"""Re-evaluate legal partition candidates in the original Problem 2 scene B.

Candidate generation never changes the input graph, evaluator, or config.  The
saved plan is exactly the plan passed to the official evaluator.
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


FIELDS = ("case", "cores", "strategy", "status", "makespan_cycles",
          "added_copy_bytes", "spill_added_copy_bytes", "scheduled_copy_bytes",
          "peak_l1_bytes", "peak_ub_bytes", "wall_seconds", "error")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", type=int, required=True)
    parser.add_argument("--cores", nargs="+", type=int, default=[5])
    args = parser.parse_args()
    project = args.project.resolve()
    sys.path.insert(0, str(project / "official" / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config

    config = project / "official" / "data" / "config.txt"
    settings = read_evaluation_config(str(config))
    scene = read_scene_b_config(str(config))
    out = project / "q2_optimization"
    out.mkdir(parents=True, exist_ok=True)
    summary = out / "candidate_summary.csv"
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
            for cores in args.cores:
                strategy = "q1_selected"
                if (case, cores, strategy) in done:
                    continue
                source = (project / "q1_optimization" / "final" / "plans" /
                          f"n{cores}" / f"{case}_multicore_res.json")
                plan = json.loads(source.read_text(encoding="utf-8"))
                folder = out / case / f"n{cores}" / strategy
                folder.mkdir(parents=True, exist_ok=True)
                (folder / source.name).write_text(json.dumps(plan, separators=(",", ":"))
                                                  + "\n", encoding="utf-8")
                row = dict.fromkeys(FIELDS, "")
                row.update(case=case, cores=cores, strategy=strategy)
                start = time.perf_counter()
                try:
                    result = evaluate_scene_b(
                        graph, plan, bandwidth=settings["bandwidth"],
                        capacity=settings["capacity"],
                        cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
                    movement = result["data_movement_bytes"]
                    row.update(status="ok", makespan_cycles=result["makespan"],
                               added_copy_bytes=movement["added_copy_bytes"],
                               spill_added_copy_bytes=movement["spill_added_copy_bytes"],
                               scheduled_copy_bytes=movement["scheduled_copy_bytes"])
                    with gzip.open(folder / "result.json.gz", "wt", encoding="utf-8",
                                   compresslevel=1) as output:
                        json.dump(result, output, ensure_ascii=False,
                                  separators=(",", ":"))
                except Exception:
                    row.update(status="error", error=traceback.format_exc()[-1600:])
                    (folder / "error.txt").write_text(row["error"], encoding="utf-8")
                row["wall_seconds"] = round(time.perf_counter() - start, 3)
                writer.writerow(row)
                stream.flush()
                print(case, cores, strategy, row["status"],
                      row["makespan_cycles"], row["wall_seconds"], flush=True)


if __name__ == "__main__":
    main()
