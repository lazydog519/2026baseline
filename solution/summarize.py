"""汇总官方评测结果；严格检查三问全部 100 例并生成真实数据图。"""

import argparse
import csv
import json
from pathlib import Path
from statistics import mean


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = {}
    for folder in args.inputs:
        with (folder / "summary.csv").open(encoding="utf-8", newline="") as fp:
            for row in csv.DictReader(fp):
                rows[(row["case"], row["variant"], int(row["cores"]))] = row

    missing = []
    data = []
    for index in range(1, 101):
        case = f"case_{index:03d}"
        required = [(case, "singlecore", 1)]
        required += [(case, "q1", n) for n in range(2, 6)]
        required += [(case, kind, n) for kind in ("q2", "q3") for n in range(1, 6)]
        bad = [key for key in required if key not in rows or rows[key]["status"] != "ok"]
        if bad:
            missing.extend(bad)
            continue
        single = float(rows[(case, "singlecore", 1)]["makespan_cycles"])
        for n in range(1, 6):
            q2 = float(rows[(case, "q2", n)]["makespan_cycles"])
            q3 = float(rows[(case, "q3", n)]["makespan_cycles"])
            q1 = (float(rows[(case, "q1", n)]["makespan_cycles"])
                  if n >= 2 else None)
            data.append({"case": case, "cores": n, "singlecore_cycles": single,
                         "q1_cycles": q1, "q2_cycles": q2, "q3_cycles": q3,
                         "q1_speedup": single / q1 if q1 else None,
                         "q2_speedup": single / q2,
                         "q3_speedup": q2 / q3,
                         "q3_cache_hit_rate": float(rows[(case, "q3", n)]["cache_hit_rate"]),
                         "q3_cache_hit_bytes": int(rows[(case, "q3", n)]["cache_hit_bytes"] or 0)})

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "per_case_metrics.csv").open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(data[0]) if data else ["case"])
        writer.writeheader()
        writer.writerows(data)
    means = {kind: {str(n): mean(row[f"{kind}_speedup"] for row in data
                                 if row["cores"] == n)
                    for n in (range(2, 6) if kind == "q1" else range(1, 6))}
             for kind in ("q1", "q2", "q3")} if data else {}
    report = {"complete_cases": len(data) // 5, "missing_jobs": len(missing),
              "first_missing": missing[:10], "arithmetic_mean_speedup": means}
    (args.output / "aggregate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if missing:
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit("Incomplete evaluation; figure generation deferred")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for kind, label in (("q1", "Q1"), ("q2", "Q2")):
        x = list(map(int, means[kind]))
        axes[0].plot(x, [means[kind][str(n)] for n in x], "o-", label=label)
    axes[0].axhline(1, color="0.5", linewidth=0.8)
    axes[0].set(xlabel="Core count", ylabel="Mean speedup vs single core", xticks=range(1, 6))
    axes[0].legend()
    x = list(map(int, means["q3"]))
    axes[1].plot(x, [means["q3"][str(n)] for n in x], "o-", color="#b05a00")
    axes[1].axhline(1, color="0.5", linewidth=0.8)
    axes[1].set(xlabel="Core count", ylabel="Mean Q3 / Q2 speedup", xticks=range(1, 6))
    fig.savefig(args.output / "mean_speedup.png", dpi=200)
    fig.savefig(args.output / "mean_speedup.pdf")
    plt.close(fig)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
