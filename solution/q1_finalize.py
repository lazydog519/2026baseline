"""Select verified Problem 1 plans and make its required 1–5 core curve."""

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    out = project / "q1_optimization" / "final"
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(project / "official" / "code"))
    from stub_multicore_cut_and_schedule import derive_multicore_plan
    from evaluation_validation import validate_task_order

    baseline_metrics = {
        (r["case"], int(r["cores"])): r
        for r in rows(project / "final_metrics" / "per_case_metrics.csv")
        if r["q1_cycles"]
    }
    baseline_runs = defaultdict(list)
    for summary in sorted(project.glob("baseline_results*/summary.csv")):
        for row in rows(summary):
            if row["variant"] == "q1" and row["status"] == "ok":
                key = row["case"], int(row["cores"])
                plan = (summary.parent / row["case"] /
                        f"q1_n{row['cores']}" /
                        f"{row['case']}_multicore_res.json")
                if plan.is_file():
                    baseline_runs[key].append((row, plan))
    candidates = defaultdict(list)
    candidate_file = project / "q1_optimization" / "candidate_summary.csv"
    for row in rows(candidate_file):
        if row["status"] != "ok":
            continue
        key = row["case"], int(row["cores"])
        plan = (project / "q1_optimization" / row["case"] /
                f"n{row['cores']}" / row["strategy"] /
                f"{row['case']}_multicore_res.json")
        if plan.is_file():
            candidates[key].append((row, plan))

    fields = ("case", "cores", "singlecore_cycles", "baseline_cycles",
              "selected_cycles", "speedup", "added_copy_bytes",
              "strategy", "source_plan")
    selected = []
    missing = []
    graph_cache = {}
    for case_id in range(1, 101):
        case = f"case_{case_id:03d}"
        for cores in range(2, 6):
            key = case, cores
            metric = baseline_metrics.get(key)
            if not metric:
                missing.append(key)
                continue
            baseline = [(row, plan) for row, plan in baseline_runs[key]
                        if int(row["makespan_cycles"]) ==
                        int(float(metric["q1_cycles"]))]
            if not baseline:
                missing.append(key)
                continue
            options = [("baseline", row, plan) for row, plan in baseline]
            options += [(row["strategy"], row, plan)
                        for row, plan in candidates[key]]
            strategy, result, source = min(
                options, key=lambda item: (int(item[1]["makespan_cycles"]),
                                           int(item[1]["added_copy_bytes"]),
                                           item[0]))
            with gzip.open(source.parent / "result.json.gz", "rt",
                           encoding="utf-8") as stream:
                official_result = json.load(stream)
            if (official_result["scene"] != "A" or
                    official_result["num_cores"] != cores or
                    official_result["makespan"] != int(result["makespan_cycles"]) or
                    official_result["data_movement_bytes"]["added_copy_bytes"] !=
                    int(result["added_copy_bytes"])):
                raise ValueError(f"{case} n{cores}: result does not match plan record")
            plan = json.loads(source.read_text(encoding="utf-8"))
            if len(plan["core_schedules"]) != cores:
                raise ValueError(f"{case} n{cores}: wrong core count")
            if case not in graph_cache:
                graph_cache[case] = json.loads(
                    (project / "official" / "data" / f"{case}.json")
                    .read_text(encoding="utf-8"))
            view = derive_multicore_plan(graph_cache[case], plan)
            validate_task_order(view)
            target = out / "plans" / f"n{cores}"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target / source.name)
            cycles = int(result["makespan_cycles"])
            selected.append({
                "case": case, "cores": cores,
                "singlecore_cycles": int(float(metric["singlecore_cycles"])),
                "baseline_cycles": int(float(metric["q1_cycles"])),
                "selected_cycles": cycles,
                "speedup": float(metric["singlecore_cycles"]) / cycles,
                "added_copy_bytes": int(result["added_copy_bytes"]),
                "strategy": strategy,
                "source_plan": str(source.relative_to(project)).replace("\\", "/"),
            })
    if missing or len(selected) != 400:
        raise ValueError(f"missing plans: {missing[:10]} (total {len(missing)})")
    with (out / "per_case_metrics.csv").open("w", encoding="utf-8",
                                               newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)

    by_core = defaultdict(list)
    for row in selected:
        by_core[row["cores"]].append(row)
    baseline_aggregate = json.loads(
        (project / "final_metrics" / "aggregate.json").read_text(encoding="utf-8"))
    means = {1: 1.0}
    baseline_means = {1: 1.0}
    for cores in range(2, 6):
        means[cores] = sum(r["speedup"] for r in by_core[cores]) / 100
        baseline_means[cores] = baseline_aggregate[
            "arithmetic_mean_speedup"]["q1"][str(cores)]
    config = project / "official" / "data" / "config.txt"
    aggregate = {
        "schema": "q1-selection-v1", "complete_cases": 100,
        "missing_jobs": len(missing), "evaluated_selections": len(selected),
        "arithmetic_mean_speedup": means,
        "baseline_arithmetic_mean_speedup": baseline_means,
        "improved_cases_by_cores": {
            n: sum(r["selected_cycles"] < r["baseline_cycles"]
                   for r in by_core[n]) for n in range(2, 6)},
        "official_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "selection_rule": "minimum official makespan; tie: minimum added COPY bytes",
    }
    (out / "aggregate.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False,
                         "font.sans-serif": ["Microsoft YaHei", "SimHei",
                                             "DejaVu Sans"],
                         "axes.unicode_minus": False})
    fig, ax = plt.subplots(figsize=(6.2, 3.8), layout="constrained")
    xs = list(range(1, 6))
    ax.plot(xs, [baseline_means[n] for n in xs], "o--", linewidth=1.6,
            label="初始基线")
    ax.plot(xs, [means[n] for n in xs], "o-", linewidth=2.2,
            label="问题一优化方案")
    ax.set(xticks=xs, xlabel="核心数", ylabel="100 例平均加速比")
    ax.set_ylim(bottom=0.85)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, loc="upper left")
    fig.savefig(out / "mean_speedup.png", dpi=240)
    fig.savefig(out / "mean_speedup.pdf")
    plt.close(fig)
    print(json.dumps(aggregate, ensure_ascii=False))


if __name__ == "__main__":
    main()
