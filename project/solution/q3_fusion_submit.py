"""Independent Problem 3 submission entrypoint.

Each invocation reads one graph and the fixed official config, constructs new
plans, and selects only by the unchanged Problem 3 simulator. No saved plan is
an input to this entrypoint, even when the experiments resume completed jobs.
"""
import argparse
import gzip
import importlib.util
import json
import sys
from pathlib import Path

from baseline import make_plan
from q3_cold import DEFAULT_CONFIG, fingerprint, solve as greedy_solve

PROJECT = Path(__file__).resolve().parents[1]
FUSION_CONFIG = PROJECT / "solution" / "q3_fusion_config.json"
sys.path[:0] = [str(PROJECT / "official" / "code"), str(PROJECT / "q3_design")]
from evaluation_validation import read_evaluation_config
from multicore_cut_evaluate_problem_2 import evaluate_scene_b
from multicore_cut_evaluate_problem_3 import (
    evaluate_problem_3, read_cache_config, read_scene_b_config,
)
from q3_pilot_solver import GraphView


def hardware_kwargs(config):
    hw = read_evaluation_config(str(config))
    return dict(bandwidth=hw["bandwidth"], capacity=hw["capacity"],
                cross_core_copy_delay=read_scene_b_config(str(config))[
                    "cross_core_copy_delay_cycles"]), read_cache_config(str(config))


def read_branch_model():
    path = PROJECT / "q3_fusion" / "branch_solver.py"
    spec = importlib.util.spec_from_file_location("q3_fusion_branch_operator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refine(graph, cores, config, stage1_plan, stage1_result, folder):
    """Refine a plan generated in this same independent case run.

    The branch search starts separately from the graph, not from stage 1.
    The two candidates meet only at final official-result selection.
    """
    folder.mkdir(parents=True, exist_ok=True)
    policy = json.loads(FUSION_CONFIG.read_text(encoding="utf-8"))
    max_feedback = policy["max_feedback_evaluations"]
    efficiency_gate = policy["normalized_efficiency_gate"]
    branch_seed = policy["branch_seed"]
    params, cache = hardware_kwargs(config)
    best_plan, best_result = stage1_plan, stage1_result
    best_key = (best_result["makespan"],
                best_result["data_movement_bytes"]["added_copy_bytes"])
    seen = {fingerprint(best_plan)}
    feedback_rows = []
    try:
        proposals = GraphView(graph).feedback(
            best_plan, best_result,
            {"max_target_tensors": policy["max_target_tensors"]}, params["bandwidth"])
        for mode, candidate, detail in proposals:
            digest = fingerprint(candidate)
            if digest in seen:
                continue
            seen.add(digest)
            row = dict(operator=mode, plan_sha256=digest, detail=detail)
            try:
                result = evaluate_problem_3(graph, candidate, **params, **cache)
                key = (result["makespan"],
                       result["data_movement_bytes"]["added_copy_bytes"])
                row.update(status="feasible", makespan=key[0],
                           cache_hit_rate=result["cache_stats"]["hit_rate"])
                if key < best_key:
                    best_plan, best_result, best_key = candidate, result, key
                    row["accepted"] = True
            except (ValueError, RuntimeError) as exc:
                row.update(status="infeasible", reason=str(exc))
            feedback_rows.append(row)
            if len(feedback_rows) >= max_feedback:
                break
    except (ValueError, RuntimeError, KeyError, IndexError) as exc:
        feedback_rows.append(dict(status="feedback_construction_failed", reason=str(exc)))

    branch_summary = None
    single_core = None
    efficiency = None
    if cores > 1:
        single_core = evaluate_problem_3(graph, make_plan(graph, 1), **params, **cache)[
            "makespan"]
        efficiency = (single_core / best_key[0]) / cores
    if cores > 1 and efficiency < efficiency_gate:
        branch = read_branch_model()
        branch.guided.original.Model = branch.BranchModel
        branch_cfg = policy["branch_search"]
        branch_out = folder / "branch_search"
        branch_summary = branch.guided.original.run(
            graph, cores, config, branch_cfg, "unsga3_npu", branch_seed, branch_out)
        candidate = json.loads((branch_out / "plan.json").read_text(encoding="utf-8"))
        with gzip.open(branch_out / "result.json.gz", "rt", encoding="utf-8") as stream:
            result = json.load(stream)
        key = (result["makespan"], result["data_movement_bytes"]["added_copy_bytes"])
        branch_summary["accepted"] = key < best_key
        if key < best_key:
            best_plan, best_result, best_key = candidate, result, key
    no_l2 = evaluate_scene_b(graph, best_plan, **params)
    assert no_l2["data_movement_bytes"] == best_result["data_movement_bytes"]
    report = dict(schema="q3-cold-fusion-v2", cold_start=True,
                  no_historical_plans_read=True, cores=cores,
                  stage1_cycles=stage1_result["makespan"],
                  final_cycles=best_result["makespan"],
                  same_plan_no_l2_cycles=no_l2["makespan"],
                  cache_hit_rate=best_result["cache_stats"]["hit_rate"],
                  cache_miss_bytes=best_result["cache_stats"]["miss_bytes"],
                  added_copy_bytes=best_result["data_movement_bytes"]["added_copy_bytes"],
                  reference_single_core_l2=single_core,
                  decision_efficiency=efficiency,
                  efficiency_gate=efficiency_gate,
                  fixed_policy=policy,
                  feedback_evaluations=feedback_rows,
                  branch_search=branch_summary,
                  final_plan_sha256=fingerprint(best_plan))
    return best_plan, best_result, no_l2, report


def solve(graph, cores, config, output, folder, search_config):
    """Full cold path used by the submission CLI and isolation test."""
    folder.mkdir(parents=True, exist_ok=True)
    stage1 = folder / "greedy"
    stage1_plan = stage1 / "plan.json"
    first_report = greedy_solve(graph, cores, PROJECT / "official" / "code",
                                config, search_config, stage1_plan, stage1)
    plan = json.loads(stage1_plan.read_text(encoding="utf-8"))
    with gzip.open(stage1 / "official_result.json.gz", "rt", encoding="utf-8") as stream:
        result = json.load(stream)
    chosen, l2, no_l2, report = refine(graph, cores, config, plan, result, folder)
    report["greedy_report"] = first_report
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(chosen, separators=(",", ":")) + "\n", encoding="utf-8")
    with gzip.open(folder / "result.json.gz", "wt", encoding="utf-8", compresslevel=1) as stream:
        json.dump(l2, stream, separators=(",", ":"))
    with gzip.open(folder / "no_l2_same_plan.json.gz", "wt", encoding="utf-8", compresslevel=1) as stream:
        json.dump(no_l2, stream, separators=(",", ":"))
    (folder / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("-n", "--num-cores", type=int, choices=range(1, 6), required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--search-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--trace-dir", type=Path)
    args = parser.parse_args()
    output = args.output or args.graph.with_name(args.graph.stem + "_multicore_res.json")
    trace = args.trace_dir or output.with_suffix("").with_name(output.stem + "_search")
    report = solve(json.loads(args.graph.read_text(encoding="utf-8")),
                   args.num_cores, args.config or args.graph.with_name("config.txt"),
                   output, trace, json.loads(args.search_config.read_text(encoding="utf-8")))
    print(json.dumps({k: report[k] for k in ("cores", "stage1_cycles", "final_cycles",
                                                  "same_plan_no_l2_cycles")}), flush=True)


if __name__ == "__main__":
    main()
