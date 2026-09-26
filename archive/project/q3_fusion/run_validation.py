"""Frozen, equal-budget development and input-selected holdout audit."""
import csv
import gzip
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = HERE.parent
sys.path[:0] = [str(P / "q3_nsga"), str(P / "solution"), str(P / "official/code")]
from multicore_cut_evaluate_problem_2 import evaluate_scene_b
from multicore_cut_evaluate_problem_3 import (
    evaluate_problem_3, read_cache_config, read_scene_b_config)
from evaluation_validation import read_evaluation_config

DEV = ("case_044", "case_074", "case_082")
# Chosen before the validation runs, using only compute-only lower-bound gaps
# and size diversity. They were not used to design this operator.
HOLDOUT = ("case_005", "case_071")
SEEDS = (17, 29, 43)
OLD = P / "q3_nsga"
FILES = [HERE / "solve.py", HERE / "experiment.json", OLD / "solve.py",
         OLD / "experiment.json", P / "q3_design/q3_pilot_solver.py",
         P / "solution/baseline.py", P / "solution/q1_optimized.py"]


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory(case, variant, seed):
    if case in DEV:
        if variant == "prior_unsga3":
            return OLD / "experiment" / case / "n5/unsga3_npu" / f"seed_{seed}"
        return HERE / "development" / case / f"seed_{seed}_v2"
    return HERE / "validation" / case / variant / f"seed_{seed}"


def execute(case, variant, seed):
    dest = directory(case, variant, seed)
    if not (dest / "run.json").exists():
        dest.mkdir(parents=True, exist_ok=True)
        script = OLD / "solve.py" if variant == "prior_unsga3" else HERE / "solve.py"
        params = OLD / "experiment.json" if variant == "prior_unsga3" else HERE / "experiment.json"
        cmd = [sys.executable, "-X", "utf8", str(script),
               str(P / f"official/data/{case}.json"), "-n", "5"]
        if variant == "prior_unsga3":
            cmd += ["--method", "unsga3_npu"]
        cmd += ["--seed", str(seed), "--output", str(dest),
                "--parameters", str(params)]
        with (dest / "console.log").open("w", encoding="utf-8") as stream:
            proc = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT)
        if proc.returncode:
            raise RuntimeError(f"{case}/{variant}/{seed} failed; inspect {dest / 'console.log'}")
    return case, variant, seed, dest


def audit(item, hardware, scene, cache):
    case, variant, seed, dest = item
    summary = json.loads((dest / "run.json").read_text(encoding="utf-8"))
    plan = json.loads((dest / "plan.json").read_text(encoding="utf-8"))
    graph = json.loads((P / f"official/data/{case}.json").read_text(encoding="utf-8"))
    assert set(plan) == {"node_to_subgraph", "core_schedules"}
    assert summary["official_calls"] == 30 and summary["invalid_records"] == 0
    assert summary["cold_start"] and not summary["historical_plans_read"]
    with gzip.open(dest / "result.json.gz", "rt", encoding="utf-8") as f:
        stored = json.load(f)
    kw = dict(bandwidth=hardware["bandwidth"], capacity=hardware["capacity"],
              cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
    fresh = evaluate_problem_3(graph, plan, **kw, **cache)
    assert json.loads(json.dumps(fresh)) == stored
    no_cache = evaluate_scene_b(graph, plan, **kw)
    assert no_cache["data_movement_bytes"] == fresh["data_movement_bytes"]
    assert all(x[k] <= hardware["capacity"][k]
               for x in fresh["memory_peak_by_core"].values()
               for k in ("L1", "UB"))
    return dict(case=case, role="development" if case in DEV else "holdout",
                variant=variant, seed=seed, makespan=fresh["makespan"],
                construction_best=summary["construction_best"],
                no_l2_same_plan=no_cache["makespan"],
                added_copy_bytes=fresh["data_movement_bytes"]["added_copy_bytes"],
                spill_added_bytes=fresh["data_movement_bytes"]["spill_added_copy_bytes"],
                miss_bytes=fresh["cache_stats"]["miss_bytes"],
                hit_rate=fresh["cache_stats"]["hit_rate"],
                calls=summary["official_calls"],
                initial_population_hashes=summary["initial_population_hashes"],
                directory=str(dest.relative_to(P)))


def main():
    output = HERE / "validation"
    output.mkdir(exist_ok=True)
    frozen = {str(f.relative_to(P)): hash_file(f) for f in FILES}
    (output / "manifest.json").write_text(json.dumps(
        {"source_sha256": frozen, "development": DEV, "holdout": HOLDOUT,
         "seeds": SEEDS, "cores": 5, "official_budget_per_search": 30,
         "holdout_selection": "top static compute-bound gap among unseen small/large cases"},
        indent=2) + "\n", encoding="utf-8")
    jobs = [(c, v, s) for c in (*DEV, *HOLDOUT)
            for s in SEEDS for v in ("prior_unsga3", "event_guided_unsga3")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, *job) for job in jobs]
        done = []
        for future in as_completed(futures):
            item = future.result()
            done.append(item)
            print("run", *item[:3], flush=True)
    hw_path = P / "official/data/config.txt"
    hardware = read_evaluation_config(str(hw_path))
    scene = read_scene_b_config(str(hw_path))
    cache = read_cache_config(str(hw_path))
    rows = [audit(x, hardware, scene, cache) for x in done]
    rows.sort(key=lambda r: (r["case"], r["seed"], r["variant"]))
    for case in (*DEV, *HOLDOUT):
        for seed in SEEDS:
            group = [r for r in rows if r["case"] == case and r["seed"] == seed]
            assert len(group) == 2
            assert group[0]["initial_population_hashes"] == group[1]["initial_population_hashes"]
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        cols = [k for k in rows[0] if k != "initial_population_hashes"]
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows({k: r[k] for k in cols} for r in rows)
    orig = json.loads((P / "official_manifest.json").read_text(encoding="utf-8"))
    assert all(hash_file(P / "official" / entry["path"]) == entry["sha256"]
               for entry in orig["files"])
    assert {str(f.relative_to(P)): hash_file(f) for f in FILES} == frozen
    (output / "verification.json").write_text(json.dumps(
        {"completed_jobs": len(rows), "rechecked_jobs": len(rows),
         "equal_initial_populations": True, "official_files_unchanged": len(orig["files"]),
         "frozen_sources_unchanged": True, "no_full_100_case_run": True},
        indent=2) + "\n", encoding="utf-8")
    print("VERIFIED", len(rows), flush=True)


if __name__ == "__main__":
    main()
