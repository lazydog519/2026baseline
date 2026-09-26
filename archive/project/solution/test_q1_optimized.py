"""Small official-evaluator smoke test for Problem 1 plan generators."""

import json
import sys
from pathlib import Path

from q1_optimized import (depth_band_plan, first_join_plan, fork_join_plan,
                          heft_task_schedule, mask_band_plan,
                          terminal_branch_plan, valley_stage_plan)


def main(official):
    sys.path.insert(0, str(official / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_1 import evaluate_scene_a, read_scene_a_config

    graph = {
        "tensors": [{"id": 1, "pos": "DDR", "size": 16},
                    {"id": 2, "pos": "UB", "size": 16},
                    {"id": 3, "pos": "UB", "size": 16},
                    {"id": 4, "pos": "DDR", "size": 16}],
        "ops": [{"id": 10, "op": "COPY_IN", "pipe": "PIPE_MTE2", "cycles": 1},
                {"id": 11, "op": "ADD", "pipe": "PIPE_V", "cycles": 4},
                {"id": 12, "op": "COPY_OUT", "pipe": "PIPE_MTE3", "cycles": 1}],
        "edges": [{"source": a, "target": b}
                  for a, b in ((1, 10), (10, 2), (2, 11), (11, 3),
                               (3, 12), (12, 4))],
    }
    config = official / "data" / "config.txt"
    settings = read_evaluation_config(str(config))
    scene = read_scene_a_config(str(config))
    for make in (first_join_plan, terminal_branch_plan, fork_join_plan,
                 lambda g, n: depth_band_plan(g, n, 4),
                 lambda g, n: valley_stage_plan(g, n, split_shared=True,
                                                narrow_rule="mode"),
                 lambda g, n: mask_band_plan(g, n, 4),
                 lambda g, n: heft_task_schedule(
                     g, mask_band_plan(g, n, 4), n),
                 lambda g, n: valley_stage_plan(g, n, split_shared=True,
                                                narrow_rule="mode",
                                                min_band_depth=8),
                 lambda g, n: depth_band_plan(g, n, 4, data_aware=True),
                 lambda g, n: mask_band_plan(g, n, 4,
                                             direction="sources")):
        plan = make(graph, 2)
        assert set(plan) == {"node_to_subgraph", "core_schedules"}
        assert set(plan["node_to_subgraph"]) == {"11"}
        result = evaluate_scene_a(
            graph, plan, bandwidth=settings["bandwidth"],
            capacity=settings["capacity"],
            cross_core_wait=scene["task_cross_core_wait_cycles"],
            same_core_wait=scene["task_same_core_wait_cycles"])
        assert result["makespan"] == 6, result["makespan"]
        assert result["data_movement_bytes"]["added_copy_bytes"] == 0
    print(json.dumps({"smoke_test": "ok", "strategies": 10,
                      "makespan_cycles": 6}))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
