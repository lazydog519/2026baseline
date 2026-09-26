"""Choose each case's best verified Scene-B plan and plot the required curve."""

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--recheck", action="store_true",
                        help="rerun the official evaluator for all selected plans")
    args = parser.parse_args()
    project = args.project.resolve()
    sys.path.insert(0, str(project / "official" / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b, read_scene_b_config

    config = project / "official" / "data" / "config.txt"
    settings = read_evaluation_config(str(config))
    scene = read_scene_b_config(str(config))
    reference = {(r["case"], int(r["cores"])): r for r in
                 read_csv(project / "final_metrics" / "per_case_metrics.csv")}
    options = defaultdict(list)
    for folder in sorted(project.glob("baseline_results*")):
        summary = folder / "summary.csv"
        if not summary.is_file():
            continue
        for row in read_csv(summary):
            if row["variant"] != "q2" or row["status"] != "ok" or int(row["cores"]) < 2:
                continue
            key = row["case"], int(row["cores"])
            if int(row["makespan_cycles"]) != int(float(reference[key]["q2_cycles"])):
                continue
            source = folder / row["case"] / f"q2_n{row['cores']}"
            plan = source / f"{row['case']}_multicore_res.json"
            result = source / "result.json.gz"
            if plan.is_file() and result.is_file():
                options[key].append(("baseline", row, plan, result))
    candidate_files = [project / "q2_optimization" / "candidate_summary.csv"]
    candidate_files.extend(sorted((project / "q2_optimization").glob("*/candidate_summary.csv")))
    for summary in candidate_files:
        if not summary.is_file():
            continue
        for row in read_csv(summary):
            if row["status"] != "ok":
                continue
            key = row["case"], int(row["cores"])
            folder = summary.parent / row["case"] / f"n{row['cores']}" / row["strategy"]
            plan = folder / f"{row['case']}_multicore_res.json"
            result = folder / "result.json.gz"
            if not plan.is_file() or not result.is_file():
                raise ValueError(f"successful candidate missing files: {folder}")
            options[key].append((row["strategy"], row, plan, result))

    out = project / "q2_optimization" / "final"
    out.mkdir(parents=True, exist_ok=True)
    rows, missing = [], []
    for index in range(1, 101):
        case = f"case_{index:03d}"
        graph = json.loads((project / "official" / "data" / f"{case}.json")
                           .read_text(encoding="utf-8"))
        for cores in range(2, 6):
            key = case, cores
            if not options[key]:
                missing.append(key)
                continue
            strategy, record, source, result_file = min(
                options[key], key=lambda item: (
                    int(item[1]["makespan_cycles"]),
                    int(item[1]["added_copy_bytes"]), item[0]))
            plan = json.loads(source.read_text(encoding="utf-8"))
            with gzip.open(result_file, "rt", encoding="utf-8") as stream:
                result = json.load(stream)
            if (result["scene"] != "B" or result["num_cores"] != cores or
                    result["makespan"] != int(record["makespan_cycles"]) or
                    result["data_movement_bytes"]["added_copy_bytes"] !=
                    int(record["added_copy_bytes"])):
                raise ValueError(f"result/summary mismatch: {case} n{cores} {strategy}")
            if args.recheck:
                check = evaluate_scene_b(
                    graph, plan, bandwidth=settings["bandwidth"],
                    capacity=settings["capacity"],
                    cross_core_copy_delay=scene["cross_core_copy_delay_cycles"])
                if (check["makespan"] != result["makespan"] or
                        check["data_movement_bytes"] != result["data_movement_bytes"] or
                        check["memory_peak_by_core"] != result["memory_peak_by_core"]):
                    raise ValueError(f"official recheck mismatch: {case} n{cores}")
            peaks = result["memory_peak_by_core"].values()
            if any(p["L1"] > settings["capacity"]["L1"] or
                   p["UB"] > settings["capacity"]["UB"] for p in peaks):
                raise ValueError(f"capacity violated: {case} n{cores}")
            target = out / "plans" / f"n{cores}" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            single = float(reference[key]["singlecore_cycles"])
            baseline = float(reference[key]["q2_cycles"])
            rows.append({"case": case, "cores": cores,
                         "singlecore_cycles": int(single),
                         "baseline_cycles": int(baseline),
                         "selected_cycles": result["makespan"],
                         "speedup": single / result["makespan"],
                         "added_copy_bytes": result["data_movement_bytes"]["added_copy_bytes"],
                         "partition_added_copy_bytes": result["data_movement_bytes"]["partition_added_copy_bytes"],
                         "spill_added_copy_bytes": result["data_movement_bytes"]["spill_added_copy_bytes"],
                         "peak_l1_bytes": max((p["L1"] for p in result["memory_peak_by_core"].values()), default=0),
                         "peak_ub_bytes": max((p["UB"] for p in result["memory_peak_by_core"].values()), default=0),
                         "strategy": strategy,
                         "source_plan": source.relative_to(project).as_posix(),
                         "source_result": result_file.relative_to(project).as_posix()})
    if missing or len(rows) != 400:
        raise ValueError(f"missing {len(missing)} cases: {missing[:10]}")
    with (out / "per_case_metrics.csv").open("w", encoding="utf-8",
                                               newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    grouped = {n: [r for r in rows if r["cores"] == n] for n in range(2, 6)}
    means = {1: 1.0, **{n: mean(r["speedup"] for r in grouped[n])
                        for n in range(2, 6)}}
    baseline_means = {1: 1.0, **{n: mean(r["singlecore_cycles"] /
                                           r["baseline_cycles"] for r in grouped[n])
                                 for n in range(2, 6)}}
    report = {"schema": "q2-selection-v1", "complete_cases": 100,
              "missing_jobs": 0, "evaluated_selections": 400,
              "arithmetic_mean_speedup": means,
              "baseline_arithmetic_mean_speedup": baseline_means,
              "improved_cases_by_cores": {
                  n: sum(r["selected_cycles"] < r["baseline_cycles"]
                         for r in grouped[n]) for n in range(2, 6)},
              "official_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
              "selection_rule": "minimum official makespan; tie: minimum added COPY bytes",
              "official_recheck": args.recheck}
    (out / "aggregate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False,
                         "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                         "axes.unicode_minus": False})
    fig, ax = plt.subplots(figsize=(6.2, 3.8), layout="constrained")
    xs = range(1, 6)
    ax.plot(xs, [baseline_means[n] for n in xs], "o--", label="初版基线")
    ax.plot(xs, [means[n] for n in xs], "o-", label="场景 B 优化方案")
    ax.set(xticks=list(xs), xlabel="核心数", ylabel="100 例平均加速比")
    ax.set_ylim(bottom=0.85)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.savefig(out / "mean_speedup.png", dpi=240)
    fig.savefig(out / "mean_speedup.pdf")
    plt.close(fig)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
