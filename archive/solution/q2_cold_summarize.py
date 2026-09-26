"""Audit cold runs and re-evaluate final plans with the original official code."""
import argparse
import csv
import gzip
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["project", "runs", "output"]:
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--recheck", action="store_true")
    parser.add_argument("--wait-for-runs", action="store_true",
                        help="audit completed independent jobs while the batch continues")
    args = parser.parse_args()
    project, root, out = args.project.resolve(), args.runs.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(project/"official"/"code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config
    from stub_multicore_cut_and_schedule import derive_multicore_plan
    from q2_cold import fingerprint
    config = project/"official"/"data"/"config.txt"
    cfg = read_evaluation_config(str(config))
    delay = read_scene_b_config(str(config))["cross_core_copy_delay_cycles"]
    manifest = read_json(project/"official_manifest.json")
    for f in manifest["files"]:
        assert hashlib.sha256((project/"official"/f["path"]).read_bytes()).hexdigest() == f["sha256"], f["path"]
    for name, digest in read_json(project/"q2_cold"/"frozen_manifest.json")["files"].items():
        assert hashlib.sha256((project/"solution"/name).read_bytes()).hexdigest() == digest, name
    reference = {(r["case"], int(r["cores"])):r for r in csv.DictReader(
        (project/"final_metrics"/"per_case_metrics.csv").open(encoding="utf-8"))}
    rows, rechecked = [], 0
    for i in range(1,101):
        name = f"case_{i:03d}"
        graph = read_json(project/"official"/"data"/f"{name}.json")
        for n in range(2,6):
            folder = root/name/f"n{n}"
            while args.wait_for_runs and not (folder/"process.json").exists():
                time.sleep(2)
            process = read_json(folder/"process.json")
            assert process["returncode"] == 0, (name,n,"solver failed")
            run = read_json(folder/"run.json")
            assert process["returncode"] == 0 and run["cold_start"]
            assert run["graph_sha256"] == hashlib.sha256(json.dumps(graph,sort_keys=True).encode()).hexdigest()
            assert run["config_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
            plan = read_json(folder/f"{name}_multicore_res.json")
            assert fingerprint(plan) == run["selected_fingerprint"]
            derive_multicore_plan(graph,plan)
            with gzip.open(folder/"official_result.json.gz","rt",encoding="utf-8") as stream:
                result = json.load(stream)
            assert result["scene"] == "B" and result["num_cores"] == n
            if args.recheck:
                check = evaluate_scene_b(graph,plan,bandwidth=cfg["bandwidth"],capacity=cfg["capacity"],cross_core_copy_delay=delay)
                for field in ["makespan","data_movement_bytes","memory_peak_by_core"]:
                    # JSON object keys are strings, unlike live integer core IDs.
                    assert json.loads(json.dumps(check[field])) == result[field], (name,n,field)
                rechecked += 1
            events = [json.loads(s) for s in (folder/"search.jsonl").read_text(encoding="utf-8").splitlines()]
            assert len(events) == run["evaluations"] <= run["search_config"]["max_evaluations"]
            successful = [r for r in events if r["status"] == "ok"]
            assert min((r["makespan_cycles"],r["added_copy_bytes"]) for r in successful) == (run["makespan_cycles"],run["added_copy_bytes"])
            assert all(r["lower_bound_cycles"] <= r["makespan_cycles"]+1e-6 for r in successful)
            assert all(a["best_cycles"] >= b["best_cycles"] for a,b in zip(successful,successful[1:]))
            baseline = reference[name,n]
            assert run["initial_cycles"] == int(float(baseline["q2_cycles"]))
            assert result["makespan"] == run["makespan_cycles"]
            assert all(v[p] <= cfg["capacity"][p] for v in result["memory_peak_by_core"].values() for p in ("L1","UB"))
            movement=result["data_movement_bytes"]
            rows.append(dict(case=name,cores=n,singlecore_cycles=int(float(baseline["singlecore_cycles"])),
                       baseline_cycles=run["initial_cycles"],makespan_cycles=run["makespan_cycles"],
                       speedup=float(baseline["singlecore_cycles"])/run["makespan_cycles"],
                       reduction_percent=100*(1-run["makespan_cycles"]/run["initial_cycles"]),
                       added_copy_bytes=movement["added_copy_bytes"],spill_bytes=movement["spill_added_copy_bytes"],
                       peak_l1_bytes=max((p["L1"] for p in result["memory_peak_by_core"].values()), default=0),
                       peak_ub_bytes=max((p["UB"] for p in result["memory_peak_by_core"].values()), default=0),
                       evaluations=run["evaluations"],bound_pruned=run["bound_pruned"],
                       invalid_candidates=run["invalid_candidates"],wall_seconds=process["process_wall_s"],
                       stop_reason=run["stop_reason"],selected=run["selected"]))
        print(name, "checked", flush=True)
    with (out/"per_case_metrics.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    grouped={n:[r for r in rows if r["cores"]==n] for n in range(2,6)}
    summary=dict(schema="q2-cold-audit-v1",complete_cases=100,missing_jobs=0,evaluated_selections=400,
                 official_recheck=args.recheck,rechecked_jobs=rechecked,official_files_unchanged=len(manifest["files"]),
                 arithmetic_mean_speedup={1:1.,**{n:statistics.mean(r["speedup"] for r in group) for n,group in grouped.items()}},
                 baseline_mean_speedup={1:1.,**{n:statistics.mean(r["singlecore_cycles"]/r["baseline_cycles"] for r in group) for n,group in grouped.items()}},
                 improved_cases={n:sum(r["makespan_cycles"]<r["baseline_cycles"] for r in group) for n,group in grouped.items()},
                 median_wall_seconds={n:statistics.median(r["wall_seconds"] for r in group) for n,group in grouped.items()},
                 max_wall_seconds=max(r["wall_seconds"] for r in rows),
                 time_capped_jobs=sum(r["stop_reason"]=="time_budget" for r in rows),
                 total_official_search_evaluations=sum(r["evaluations"] for r in rows),
                 total_pruned_candidates=sum(r["bound_pruned"] for r in rows),
                 infeasible_candidates=sum(r["invalid_candidates"] for r in rows),
                 cold_start=True,search_config=read_json(project/"solution"/"q2_cold_config.json"))
    (out/"aggregate.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))


if __name__=="__main__":
    main()
