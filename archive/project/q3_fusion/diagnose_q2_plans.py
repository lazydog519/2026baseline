"""Offline diagnostic only: replay prior Q2 plans in the unchanged Q3 evaluator.

These saved plans are never read by the independent Q3 submission solver.
"""
import argparse
import csv
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def evaluate_case(case):
    sys.path.insert(0, str(PROJECT / "official" / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_3 import (
        evaluate_problem_3, read_cache_config, read_scene_b_config,
    )

    data = PROJECT / "official" / "data"
    config = data / "config.txt"
    graph = json.loads((data / f"{case}.json").read_text(encoding="utf-8"))
    plan = json.loads((PROJECT / "q2_cold" / "full" / case / "n5" /
                       f"{case}_multicore_res.json").read_text(encoding="utf-8"))
    settings = read_evaluation_config(str(config))
    delay = read_scene_b_config(str(config))["cross_core_copy_delay_cycles"]
    kwargs = dict(bandwidth=settings["bandwidth"], capacity=settings["capacity"],
                  cross_core_copy_delay=delay, **read_cache_config(str(config)))
    result = evaluate_problem_3(graph, plan, **kwargs)
    return dict(case=case, q3_cycles=result["makespan"],
                added_copy_bytes=result["data_movement_bytes"]["added_copy_bytes"],
                hit_rate=result["cache_stats"]["hit_rate"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cases", nargs="*", default=None)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    cases = a.cases or [f"case_{i:03d}" for i in range(1, 101)]
    with (PROJECT / "final_metrics" / "per_case_metrics.csv").open(newline="", encoding="utf-8") as stream:
        single = {r["case"]: float(r["singlecore_cycles"]) for r in csv.DictReader(stream)
                  if int(r["cores"]) == 1}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(evaluate_case, case): case for case in cases}
        for future in as_completed(futures):
            row = future.result()
            row["singlecore_cycles"] = single[row["case"]]
            row["speedup"] = row["singlecore_cycles"] / row["q3_cycles"]
            rows.append(row)
            with a.output.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(sorted(rows, key=lambda r: r["case"]))
            print(json.dumps(dict(completed=len(rows), case=row["case"],
                                  speedup=row["speedup"])), flush=True)
    print(json.dumps(dict(cases=len(rows), arithmetic_mean_speedup=sum(
        r["speedup"] for r in rows) / len(rows))), flush=True)


if __name__ == "__main__":
    main()
