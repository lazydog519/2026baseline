"""Small official-evaluator checks before the full experiment (stdlib only)."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from q2_cold import Problem, fingerprint, solve


def tiny_graph(branches):
    tensors = [{"id": 1, "pos": "DDR", "size": 16},
               {"id": 2, "pos": "UB", "size": 16}]
    ops = [{"id": 100, "op": "COPY_IN", "pipe": "PIPE_MTE2", "cycles": 1}]
    edges = [{"source": 1, "target": 100}, {"source": 100, "target": 2}]
    for i in range(branches):
        a, b, op, out = 3+2*i, 4+2*i, 101+2*i, 102+2*i
        tensors += [{"id": a, "pos": "UB", "size": 16}, {"id": b, "pos": "DDR", "size": 16}]
        ops += [{"id": op, "op": "ADD", "pipe": "PIPE_V", "cycles": 4},
                {"id": out, "op": "COPY_OUT", "pipe": "PIPE_MTE3", "cycles": 1}]
        edges += [{"source": 2, "target": op}, {"source": op, "target": a},
                  {"source": a, "target": out}, {"source": out, "target": b}]
    return {"tensors": tensors, "ops": ops, "edges": edges}


def main():
    project = Path(__file__).resolve().parents[1]
    params = json.loads((project/"solution"/"q2_cold_config.json").read_text())
    params.update(max_evaluations=8, max_seconds=180)
    sys.path.insert(0, str(project/"official"/"code"))
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b
    from stub_multicore_cut_and_schedule import derive_multicore_plan
    from baseline import make_plan
    pressure = {
        "tensors": [{"id": i, "pos": "DDR" if i in (1,6) else "UB",
                     "size": 50000 if i < 5 else 16} for i in range(1,7)],
        "ops": [{"id": 100+i, "op": "COPY_IN" if i == 0 else "COPY_OUT" if i == 4 else "ADD",
                 "pipe": "PIPE_MTE2" if i == 0 else "PIPE_MTE3" if i == 4 else "PIPE_V", "cycles": 4}
                for i in range(5)],
        "edges": [{"source": a, "target": b} for a,b in
                  [(1,100),(100,2),(2,101),(101,3),(3,102),(102,4),(2,103),(4,103),(103,5),(5,104),(104,6)]]}
    result = evaluate_scene_b(pressure, make_plan(pressure,2), bandwidth=60,
                              capacity={"L1":524288,"UB":131072}, cross_core_copy_delay=500)
    assert result["data_movement_bytes"]["spill_added_copy_bytes"] > 0
    assert all(p["UB"]<=131072 for p in result["memory_peak_by_core"].values())
    bad = {"node_to_subgraph":{"101":0,"102":1,"103":0}, "core_schedules":[[0],[1]]}
    try:
        derive_multicore_plan(pressure,bad)
    except (ValueError, RuntimeError):
        pass
    else:
        raise AssertionError("contraction cycle was not rejected")
    with tempfile.TemporaryDirectory(prefix="huawei_cold_check_") as tmp:
        root = Path(tmp)
        saved = {}
        for index in [1, 3, 3, 1]:
            graph = tiny_graph(index)
            before = json.dumps(graph, sort_keys=True)
            folder = root/f"run{len(list(root.iterdir()))}"
            report = solve(graph, 2, project/"official"/"code", project/"official"/"data"/"config.txt",
                           params, folder/"plan.json", folder)
            plan = json.loads((folder/"plan.json").read_text())
            assert json.dumps(graph, sort_keys=True) == before
            pair = (fingerprint(plan), report["makespan_cycles"])
            assert index not in saved or saved[index] == pair, "case-order leakage"
            saved[index] = pair
            if index == 1:
                assert report["makespan_cycles"] == 6, "official appendix minimal result differs"
        # Copy only the executable dependencies, official code, and input/config.
        # No historical result directory exists in this standalone package.
        isolated = root/"isolated"
        isolated.mkdir()
        for name in ["q2_cold.py", "q2_cold_config.json", "q1_optimized.py", "baseline.py"]:
            shutil.copy2(project/"solution"/name, isolated/name)
        shutil.copytree(project/"official"/"code", isolated/"official_code", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(project/"official"/"data"/"config.txt", isolated/"config.txt")
        (isolated/"renamed_input.json").write_text(json.dumps(tiny_graph(3)))
        subprocess.run([sys.executable, str(isolated/"q2_cold.py"), str(isolated/"renamed_input.json"),
                        "-n", "2", "--official-code", str(isolated/"official_code"),
                        "-o", str(isolated/"out.json")], check=True, capture_output=True)
        assert fingerprint(json.loads((isolated/"out.json").read_text())) == saved[3][0]
    print("PASS: official minimal graph=6 cycles; shared-input accounting; legal spill and capacity; contraction-cycle rejection; graph unchanged; case-order independence; isolated renamed-input execution")


if __name__ == "__main__":
    main()
