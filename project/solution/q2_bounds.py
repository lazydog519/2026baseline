"""Optimistic 5-core speedup ceiling from immutable work and dependencies."""

import csv
import json
import sys
from pathlib import Path
from statistics import mean

from q1_optimized import compute_dag, topological_depth


def assert_original_copies_use_ddr(graph):
    tensor_pos = {t["id"]: t["pos"] for t in graph["tensors"]}
    inputs, outputs = {}, {}
    for edge in graph["edges"]:
        inputs.setdefault(edge["target"], []).append(edge["source"])
        outputs.setdefault(edge["source"], []).append(edge["target"])
    for op in graph["ops"]:
        if op["op"] == "COPY_IN" and not any(
                tensor_pos.get(tid) == "DDR" for tid in inputs.get(op["id"], [])):
            raise ValueError(f"COPY_IN without DDR source: {op['id']}")
        if op["op"] == "COPY_OUT" and not any(
                tensor_pos.get(tid) == "DDR" for tid in outputs.get(op["id"], [])):
            raise ValueError(f"COPY_OUT without DDR sink: {op['id']}")


def main():
    project = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(project / "official" / "code"))
    from multicore_cut_evaluate_problem_1 import _copy_traffic_bytes
    single = {r["case"]: float(r["singlecore_cycles"])
              for r in csv.DictReader((project / "final_metrics" / "per_case_metrics.csv")
                                     .open(encoding="utf-8", newline=""))
              if r["cores"] == "5"}
    rows = []
    for index in range(1, 101):
        case = f"case_{index:03d}"
        graph = json.loads((project / "official" / "data" / f"{case}.json")
                           .read_text(encoding="utf-8"))
        assert_original_copies_use_ddr(graph)
        ops, pred, succ = compute_dag(graph)
        order, _ = topological_depth(ops, pred, succ)
        path = {}
        for oid in order:
            path[oid] = ops[oid]["cycles"] + max(
                (path[p] for p in pred[oid]), default=0)
        compute_work = {
            pipe: sum(op["cycles"] for op in ops.values()
                      if op["pipe"] == pipe) / 5
            for pipe in ("PIPE_M", "PIPE_V")}
        ddr = _copy_traffic_bytes(graph) / 60
        lower = max(max(path.values(), default=0), ddr, *compute_work.values())
        rows.append({"case": case, "singlecore_cycles": single[case],
                     "critical_path_cycles": max(path.values(), default=0),
                     "matrix_work_over_5": compute_work["PIPE_M"],
                     "vector_work_over_5": compute_work["PIPE_V"],
                     "original_ddr_bytes_over_60": ddr,
                     "lower_bound_cycles": lower,
                     "speedup_upper_bound": single[case] / lower})
    out = project / "q2_optimization"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "optimistic_bounds.csv").open("w", encoding="utf-8",
                                               newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {"core_count": 5, "cases": len(rows),
              "mean_speedup_upper_bound": mean(r["speedup_upper_bound"]
                                                for r in rows),
              "cases_with_upper_bound_below_6": sum(
                  r["speedup_upper_bound"] < 6 for r in rows),
              "method": "max(longest compute path, PIPE_M work/5, "
                        "PIPE_V work/5, original DDR bytes/60)"}
    (out / "optimistic_bounds.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
