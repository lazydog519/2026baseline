"""Verify n5 band plans with unused trailing cores removed for n2–n4."""

import argparse
import csv
import gzip
import json
import sys
import time
import traceback
from pathlib import Path


FIELDS = ("case", "cores", "strategy", "status", "makespan_cycles",
          "added_copy_bytes", "spill_added_copy_bytes", "source_strategy",
          "wall_seconds", "error")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", type=int, default=list(range(1, 101)))
    parser.add_argument("--source-family", choices=("band", "data_band"),
                        default="band")
    args = parser.parse_args()
    project = args.project.resolve()
    sys.path.insert(0, str(project / "official" / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config

    config = project / "official" / "data" / "config.txt"
    settings = read_evaluation_config(str(config))
    scene = read_scene_b_config(str(config))
    source_root = project / "q2_optimization" / args.source_family
    rows = list(csv.DictReader((source_root / "candidate_summary.csv")
                               .open(encoding="utf-8", newline="")))
    by_case = {}
    for row in rows:
        if row["status"] == "ok" and row["cores"] == "5":
            by_case.setdefault(row["case"], []).append(row)
    root = (project / "q2_optimization" /
            ("transfer" if args.source_family == "band" else "transfer_data_band"))
    root.mkdir(parents=True, exist_ok=True)
    summary = root / "candidate_summary.csv"
    done = {}
    if summary.exists():
        with summary.open(encoding="utf-8", newline="") as stream:
            done = {(r["case"], int(r["cores"]), r["source_strategy"])
                    for r in csv.DictReader(stream) if r["status"] == "ok"}
    with summary.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if stream.tell() == 0:
            writer.writeheader()
        for index in args.cases:
            case = f"case_{index:03d}"
            graph = json.loads((project / "official" / "data" / f"{case}.json")
                               .read_text(encoding="utf-8"))
            for cores in (2, 3, 4):
                choices = [r for r in by_case.get(case, [])
                           if int(r["active_cores"]) <= cores]
                if not choices:
                    raise ValueError(f"no complete band candidates: {case} n{cores}")
                best = min(choices, key=lambda r: (int(r["makespan_cycles"]),
                                                   int(r["added_copy_bytes"]),
                                                   r["strategy"]))
                if (case, cores, best["strategy"]) in done:
                    continue
                strategy = f"{best['strategy']}_trimmed"
                row = dict.fromkeys(FIELDS, "")
                row.update(case=case, cores=cores, strategy=strategy,
                           source_strategy=best["strategy"])
                folder = root / case / f"n{cores}" / strategy
                folder.mkdir(parents=True, exist_ok=True)
                source = (source_root / case / "n5" / best["strategy"] /
                          f"{case}_multicore_res.json")
                plan = json.loads(source.read_text(encoding="utf-8"))
                if any(plan["core_schedules"][cores:]):
                    raise ValueError(f"nonempty trailing cores: {source}")
                plan["core_schedules"] = plan["core_schedules"][:cores]
                (folder / f"{case}_multicore_res.json").write_text(
                    json.dumps(plan, separators=(",", ":")) + "\n",
                    encoding="utf-8")
                start = time.perf_counter()
                try:
                    result = evaluate_scene_b(
                        graph, plan, bandwidth=settings["bandwidth"],
                        capacity=settings["capacity"],
                        cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
                    movement = result["data_movement_bytes"]
                    if (result["makespan"] != int(best["makespan_cycles"]) or
                            movement["added_copy_bytes"] != int(best["added_copy_bytes"])):
                        raise ValueError("trimming idle cores changed official result")
                    row.update(status="ok", makespan_cycles=result["makespan"],
                               added_copy_bytes=movement["added_copy_bytes"],
                               spill_added_copy_bytes=movement["spill_added_copy_bytes"])
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
