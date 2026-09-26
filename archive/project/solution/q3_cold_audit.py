"""Independently replay every selected Q3 plan with the untouched official code."""
import argparse
import csv
import gzip
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def recheck(job):
    project, roots, case, cores, single = job
    sys.path.insert(0, str(project / "official" / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b
    from multicore_cut_evaluate_problem_3 import (
        evaluate_problem_3, read_cache_config, read_scene_b_config,
    )

    name = f"case_{case:03d}"
    folder = next((root / name / f"n{cores}" for root in roots
                   if (root / name / f"n{cores}" / "run.json").exists()), None)
    if folder is None:
        raise FileNotFoundError(f"{name}/n{cores}: no completed run")
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    process = json.loads((folder / "process.json").read_text(encoding="utf-8"))
    assert process["returncode"] == 0 and run["cold_start"]
    assert run["schema"] == "q3-cold-fusion-v1" and run["cores"] == cores
    plan = json.loads((folder / f"{name}_multicore_res.json").read_text(encoding="utf-8"))
    graph = json.loads((project / "official" / "data" / f"{name}.json").read_text(encoding="utf-8"))
    config = project / "official" / "data" / "config.txt"
    hw = read_evaluation_config(str(config))
    scene = read_scene_b_config(str(config))
    params = dict(bandwidth=hw["bandwidth"], capacity=hw["capacity"],
                  cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
    l2 = evaluate_problem_3(graph, plan, **params, **read_cache_config(str(config)))
    no_l2 = evaluate_scene_b(graph, plan, **params)
    with gzip.open(folder / "official_result.json.gz", "rt", encoding="utf-8") as stream:
        assert l2 == json.load(stream)
    assert l2["makespan"] == run["makespan_cycles"]
    assert l2["data_movement_bytes"] == no_l2["data_movement_bytes"]
    assert all(values[key] <= hw["capacity"][key]
               for values in l2["memory_peak_by_core"].values()
               for key in ("L1", "UB"))
    return dict(case=name, cores=cores, singlecore_reference_cycles=single[name],
                q3_l2_cycles=l2["makespan"], same_plan_no_l2_cycles=no_l2["makespan"],
                speedup_vs_reference=single[name] / l2["makespan"],
                same_plan_l2_gain=no_l2["makespan"] / l2["makespan"],
                added_copy_bytes=l2["data_movement_bytes"]["added_copy_bytes"],
                spill_added_copy_bytes=l2["data_movement_bytes"]["spill_added_copy_bytes"],
                cache_hit_rate=l2["cache_stats"]["hit_rate"],
                cache_hit_bytes=l2["cache_stats"]["hit_bytes"],
                cache_miss_bytes=l2["cache_stats"]["miss_bytes"],
                official_search_calls=run["evaluations"],
                invalid_candidates=run["invalid_candidates"],
                selected=run["selected"], plan_sha256=hashlib.sha256(
                    json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cores", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--cases", type=int, nargs="+", default=list(range(1, 101)))
    parser.add_argument("--workers", type=int, default=4)
    a = parser.parse_args()
    project = a.project.resolve()
    roots = [r.resolve() for r in a.runs]
    a.output.mkdir(parents=True, exist_ok=True)
    with (project / "final_metrics" / "per_case_metrics.csv").open(
            newline="", encoding="utf-8") as stream:
        single = {r["case"]: float(r["singlecore_cycles"])
                  for r in csv.DictReader(stream) if int(r["cores"]) == 1}
    jobs = [(project, roots, case, n, single) for case in a.cases for n in a.cores]
    rows = []
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(recheck, job) for job in jobs]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            rows.sort(key=lambda r: (r["case"], r["cores"]))
            with (a.output / "audit_progress.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            print(row["case"], row["cores"], row["q3_l2_cycles"], flush=True)
    assert len(rows) == len(jobs)
    by_core = {str(n): [r for r in rows if r["cores"] == n] for n in a.cores}
    manifest = json.loads((project / "official_manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        file = project / "official" / entry["path"]
        assert hashlib.sha256(file.read_bytes()).hexdigest() == entry["sha256"]
    aggregate = dict(schema="q3-cold-audit-v1", complete_cases=len(a.cases),
                     selected_cores=a.cores, expected_jobs=len(jobs), missing_jobs=0,
                     rechecked_jobs=len(rows), official_files_unchanged=len(manifest["files"]),
                     arithmetic_mean_speedup={n: sum(r["speedup_vs_reference"] for r in group) / len(group)
                                              for n, group in by_core.items()},
                     arithmetic_mean_same_plan_l2_gain={n: sum(r["same_plan_l2_gain"] for r in group) / len(group)
                                                        for n, group in by_core.items()},
                     q2_five_core_comparison=4.246277560520675,
                     source_sha256={str(file.relative_to(project)): hashlib.sha256(file.read_bytes()).hexdigest()
                                    for file in (project / "solution" / "q3_cold.py",
                                                 project / "solution" / "q3_cold_config.json")})
    (a.output / "aggregate.json").write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(aggregate), flush=True)


if __name__ == "__main__":
    main()
