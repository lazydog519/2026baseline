"""One-operation causal trace from the frozen cold-start case_044 run."""
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = HERE.parent
sys.path[:0] = [str(P / "solution"), str(P / "official/code")]
from multicore_cut_evaluate_problem_2 import evaluate_scene_b
from multicore_cut_evaluate_problem_3 import (
    evaluate_problem_3, read_cache_config, read_scene_b_config)
from evaluation_validation import read_evaluation_config


def main():
    run = HERE / "branch_development/case_044/seed_29"
    events = [json.loads(line) for line in (run / "evaluations.jsonl").read_text().splitlines()]
    child_row = next(e for e in events if e["evaluation"] == 25)
    assert child_row["details"]["operator"] == "root_separator_branch_split"
    assert child_row["details"]["crossover"] is None
    with gzip.open(run / "candidates.jsonl.gz", "rt", encoding="utf-8") as f:
        candidates = [json.loads(line) for line in f]
    parent = candidates[child_row["details"]["parent"]]["plan"]
    child = json.loads((run / "plan.json").read_text(encoding="utf-8"))
    graph_path = P / "official/data/case_044.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    hardware_path = P / "official/data/config.txt"
    hw = read_evaluation_config(str(hardware_path))
    sc = read_scene_b_config(str(hardware_path))
    kw = dict(bandwidth=hw["bandwidth"], capacity=hw["capacity"],
              cross_core_copy_delay=sc["cross_core_copy_delay_cycles"])
    cache = read_cache_config(str(hardware_path))
    tensor = 1000000049
    details = {}
    for label, plan in (("parent", parent), ("child", child)):
        result = evaluate_problem_3(graph, plan, **kw, **cache)
        no_l2 = evaluate_scene_b(graph, plan, **kw)
        assert result["data_movement_bytes"] == no_l2["data_movement_bytes"]
        relevant = [dict(time=e["time"], event=e["event"],
                         core=e.get("core_id"), bytes=e["size_bytes"])
                    for e in result["cache_events"] if e["tensor_id"] == tensor]
        details[label] = dict(makespan=result["makespan"],
                              no_l2_same_plan=no_l2["makespan"],
                              added_copy_bytes=result["data_movement_bytes"]["added_copy_bytes"],
                              cache_miss_bytes=result["cache_stats"]["miss_bytes"],
                              cache_hit_bytes=result["cache_stats"]["hit_bytes"],
                              cross_transfers=len(result["cross_core_transfers"]),
                              core_finish=[max((o["end"] for o in c["ops"]), default=0)
                                           for c in result["per_core_timeline"]],
                              tensor_events=relevant)
        (HERE / f"branch_validation/mechanism_{label}_plan.json").write_text(
            json.dumps(plan, separators=(",", ":")) + "\n", encoding="utf-8")
    assert details["parent"]["makespan"] == 58819
    assert details["child"]["makespan"] == 27784
    out = dict(scope="one root-separator mutation in a cold-start run; no crossover",
               case="case_044", cores=5, seed=29, selected_evaluation=25,
               parent_index=child_row["details"]["parent"], tensor_id=tensor,
               tensor_size_bytes=73728, mutation=child_row["details"],
               graph_sha256=hashlib.sha256(graph_path.read_bytes()).hexdigest(),
               **details)
    (HERE / "branch_validation/mechanism.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"parent": details["parent"]["makespan"],
                      "child": details["child"]["makespan"],
                      "no_l2_parent": details["parent"]["no_l2_same_plan"],
                      "no_l2_child": details["child"]["no_l2_same_plan"]}))


if __name__ == "__main__":
    main()
