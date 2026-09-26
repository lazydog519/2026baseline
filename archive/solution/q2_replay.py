"""Test selected Q1 candidate partitions under the original Scene-B evaluator."""

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
          "added_copy_bytes", "spill_added_copy_bytes", "q1_cycles",
          "wall_seconds", "error")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", type=int, required=True)
    parser.add_argument("--cores", nargs="+", type=int, default=[5])
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()
    project = args.project.resolve()
    sys.path.insert(0, str(project / "official" / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config

    config = project / "official" / "data" / "config.txt"
    settings = read_evaluation_config(str(config))
    scene = read_scene_b_config(str(config))
    with (project / "q1_optimization" / "candidate_summary.csv").open(
            encoding="utf-8", newline="") as stream:
        q1_rows = list(csv.DictReader(stream))
    root = project / "q2_optimization" / "replay"
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
                choices = [r for r in q1_rows if r["case"] == case and
                           int(r["cores"]) == cores and r["status"] == "ok"]
                choices.sort(key=lambda r: (int(r["makespan_cycles"]),
                                            int(r["added_copy_bytes"]), r["strategy"]))
                for source_row in choices[:args.top_k]:
                    strategy = source_row["strategy"]
                    if (case, cores, strategy) in done:
                        continue
                    row = dict.fromkeys(FIELDS, "")
                    row.update(case=case, cores=cores, strategy=strategy,
                               q1_cycles=source_row["makespan_cycles"])
                    source = (project / "q1_optimization" / case / f"n{cores}" /
                              strategy / f"{case}_multicore_res.json")
                    plan = json.loads(source.read_text(encoding="utf-8"))
                    fingerprint = json.dumps(plan, sort_keys=True)
                    folder = root / case / f"n{cores}" / strategy
                    start = time.perf_counter()
                    try:
                        if fingerprint in seen:
                            row["status"] = "duplicate"
                            continue
                        seen.add(fingerprint)
                        folder.mkdir(parents=True, exist_ok=True)
                        (folder / source.name).write_text(
                            json.dumps(plan, separators=(",", ":")) + "\n",
                            encoding="utf-8")
                        result = evaluate_scene_b(
                            graph, plan, bandwidth=settings["bandwidth"],
                            capacity=settings["capacity"],
                            cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
                        movement = result["data_movement_bytes"]
                        row.update(status="ok", makespan_cycles=result["makespan"],
                                   added_copy_bytes=movement["added_copy_bytes"],
                                   spill_added_copy_bytes=movement["spill_added_copy_bytes"])
                        with gzip.open(folder / "result.json.gz", "wt",
                                       encoding="utf-8", compresslevel=1) as output:
                            json.dump(result, output, ensure_ascii=False,
                                      separators=(",", ":"))
                    except Exception:
                        row.update(status="error", error=traceback.format_exc()[-1600:])
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
