"""Equal-budget branch-operator validation; no cross-case plan reuse."""
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
sys.path[:0] = [str(P / "solution"), str(P / "official/code")]
from multicore_cut_evaluate_problem_2 import evaluate_scene_b
from multicore_cut_evaluate_problem_3 import (
    evaluate_problem_3, read_cache_config, read_scene_b_config)
from evaluation_validation import read_evaluation_config

DEV = ("case_005", "case_044", "case_071", "case_074", "case_082")
# Selected from graph-only compute lower-bound gap and input size, before
# running the frozen branch solver on these instances.
HOLDOUT = ("case_069", "case_086")
SEEDS = (17, 29, 43)
OUT = HERE / "branch_validation"
FILES = [HERE / "branch_solver.py", HERE / "branch_experiment.json",
         HERE / "solve.py", P / "q3_nsga/solve.py",
         P / "q3_nsga/experiment.json", P / "q3_design/q3_pilot_solver.py",
         P / "solution/baseline.py", P / "solution/q1_optimized.py"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory(case, variant, seed):
    if variant == "branch" and case in DEV:
        return HERE / "branch_development" / case / f"seed_{seed}"
    if variant == "prior" and case in ("case_044", "case_074", "case_082"):
        return P / "q3_nsga/experiment" / case / "n5/unsga3_npu" / f"seed_{seed}"
    if variant == "prior" and case in ("case_005", "case_071"):
        return HERE / "validation" / case / "prior_unsga3" / f"seed_{seed}"
    return OUT / case / variant / f"seed_{seed}"


def execute(case, variant, seed):
    dest = directory(case, variant, seed)
    if not (dest / "run.json").exists():
        dest.mkdir(parents=True, exist_ok=True)
        script = HERE / "branch_solver.py" if variant == "branch" else P / "q3_nsga/solve.py"
        params = (HERE / "branch_experiment.json" if variant == "branch"
                  else P / "q3_nsga/experiment.json")
        cmd = [sys.executable, "-X", "utf8", str(script),
               str(P / f"official/data/{case}.json"), "-n", "5"]
        if variant == "prior":
            cmd += ["--method", "unsga3_npu"]
        cmd += ["--seed", str(seed), "--output", str(dest),
                "--parameters", str(params)]
        with (dest / "console.log").open("w", encoding="utf-8") as log:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        if proc.returncode:
            raise RuntimeError(f"{case}/{variant}/{seed}: {dest / 'console.log'}")
    return case, variant, seed, dest


def audit(job, hardware, scene, cache):
    case, variant, seed, dest = job
    summary = json.loads((dest / "run.json").read_text(encoding="utf-8"))
    assert summary["official_calls"] == 30
    assert summary["cold_start"] and not summary["historical_plans_read"]
    plan = json.loads((dest / "plan.json").read_text(encoding="utf-8"))
    assert set(plan) == {"node_to_subgraph", "core_schedules"}
    graph = json.loads((P / f"official/data/{case}.json").read_text(encoding="utf-8"))
    kw = dict(bandwidth=hardware["bandwidth"], capacity=hardware["capacity"],
              cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
    result = evaluate_problem_3(graph, plan, **kw, **cache)
    with gzip.open(dest / "result.json.gz", "rt", encoding="utf-8") as f:
        assert json.loads(json.dumps(result)) == json.load(f)
    paired = evaluate_scene_b(graph, plan, **kw)
    assert result["data_movement_bytes"] == paired["data_movement_bytes"]
    assert all(x[k] <= hardware["capacity"][k]
               for x in result["memory_peak_by_core"].values()
               for k in ("L1", "UB"))
    return dict(case=case, role="development" if case in DEV else "algorithm_holdout",
                variant=variant, seed=seed, makespan=result["makespan"],
                no_l2_same_plan=paired["makespan"],
                construction_best=summary["construction_best"],
                added_copy_bytes=result["data_movement_bytes"]["added_copy_bytes"],
                spill_added_bytes=result["data_movement_bytes"]["spill_added_copy_bytes"],
                cache_miss_bytes=result["cache_stats"]["miss_bytes"],
                cache_hit_rate=result["cache_stats"]["hit_rate"],
                cross_transfers=len(result["cross_core_transfers"]),
                invalid=summary["invalid_records"],
                calls=summary["official_calls"],
                initial_hashes=summary["initial_population_hashes"],
                run_directory=str(dest.relative_to(P)))


def main():
    OUT.mkdir(exist_ok=True)
    frozen = {str(f.relative_to(P)): sha(f) for f in FILES}
    (OUT / "manifest.json").write_text(json.dumps(dict(
        source_sha256=frozen, development=DEV, algorithm_holdout=HOLDOUT,
        seeds=SEEDS, cores=5, official_budget_per_search=30,
        selection="input-only compute lower-bound gap plus graph-size diversity"),
        indent=2) + "\n", encoding="utf-8")
    jobs = [(case, variant, seed) for case in (*DEV, *HOLDOUT)
            for seed in SEEDS for variant in ("prior", "branch")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        completed = []
        for future in as_completed([pool.submit(execute, *j) for j in jobs]):
            item = future.result()
            completed.append(item)
            print("run", *item[:3], flush=True)
    hardware_file = P / "official/data/config.txt"
    hardware = read_evaluation_config(str(hardware_file))
    scene = read_scene_b_config(str(hardware_file))
    cache = read_cache_config(str(hardware_file))
    rows = [audit(job, hardware, scene, cache) for job in completed]
    rows.sort(key=lambda r: (r["case"], r["seed"], r["variant"]))
    for case in (*DEV, *HOLDOUT):
        for seed in SEEDS:
            pair = [r for r in rows if r["case"] == case and r["seed"] == seed]
            assert len(pair) == 2
            assert pair[0]["initial_hashes"] == pair[1]["initial_hashes"]
    cols = [k for k in rows[0] if k != "initial_hashes"]
    with (OUT / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, cols)
        writer.writeheader()
        writer.writerows({k: r[k] for k in cols} for r in rows)
    orig = json.loads((P / "official_manifest.json").read_text(encoding="utf-8"))
    assert all(sha(P / "official" / entry["path"]) == entry["sha256"]
               for entry in orig["files"])
    assert {str(f.relative_to(P)): sha(f) for f in FILES} == frozen
    (OUT / "verification.json").write_text(json.dumps(dict(
        jobs=len(rows), independently_rechecked=len(rows),
        paired_no_l2_rechecked=len(rows), equal_initial_populations=True,
        all_30_calls=True, original_files_unchanged=len(orig["files"]),
        source_frozen=True, full_100_case_run=False), indent=2) + "\n",
        encoding="utf-8")
    print("VERIFIED", len(rows), flush=True)


if __name__ == "__main__":
    main()
