"""Render the report table and measured statistics from the frozen Q2 outputs."""
import csv
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def main():
    aggregate = json.loads((PACKAGE / "results/aggregate.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((PACKAGE / "results/per_case_metrics.csv").open(encoding="utf-8-sig")))
    case = next(row for row in rows if row["case"] == "case_044" and int(row["cores"]) == 5)
    table = [
        "| 核数 | 初始方案平均加速比 | CILC 平均加速比 | 相对初始改善例数 | 进程耗时中位数（秒） | 平均局部边字节比例 | 85%峰值线内例数 | spill 总字节 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cores in range(2, 6):
        key = str(cores)
        table.append(
            f"| {cores} | {aggregate['initial_mean_speedup'][key]:.6f} "
            f"| **{aggregate['mean_speedup'][key]:.6f}** "
            f"| {aggregate['improved_vs_initial'][key]}/100 "
            f"| {aggregate['median_wall_seconds'][key]:.2f} "
            f"| {aggregate['mean_locality_ratio'][key]:.3f} "
            f"| {aggregate['buffer85_ok_cases'][key]}/100 "
            f"| {aggregate['total_spill_bytes'][key]:,} |"
        )
    text = (PACKAGE / "solution/q2_report_template.md").read_text(encoding="utf-8")
    replacements = {
        "{{RESULT_TABLE}}": "\n".join(table),
        "{{TOTAL_EVALUATIONS}}": str(aggregate["total_evaluations"]),
        "{{SPEEDUP_5}}": f"{aggregate['mean_speedup']['5']:.6f}",
        "{{CASE_INITIAL}}": str(case["initial_cycles"]),
        "{{CASE_SELECTED}}": str(case["makespan_cycles"]),
        "{{CASE_SPEEDUP}}": f"{float(case['speedup']):.6f}",
    }
    for marker, value in replacements.items():
        text = text.replace(marker, value)
    if "{{" in text:
        raise ValueError("Unexpanded report marker remains")
    (PACKAGE / "技术思路稿-问题二独立求解.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
