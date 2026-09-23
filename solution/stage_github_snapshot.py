"""把已通过官方评测的 A 题基线结果整理到独立 Git 仓库。"""

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def copy(source, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    src, dst = args.source.resolve(), args.dest.resolve()
    rows = {}
    for folder in sorted(src.glob("baseline_results*")):
        summary = folder / "summary.csv"
        if not summary.is_file():
            continue
        with summary.open(encoding="utf-8", newline="") as fp:
            for row in csv.DictReader(fp):
                if not row.get("status"):
                    continue
                key = (row["case"], row["variant"], int(row["cores"]))
                if row["status"] == "ok":
                    result = folder / row["case"] / f"{row['variant']}_n{row['cores']}" / "result.json.gz"
                    if result.is_file():
                        rows[key] = (row, folder)

    expected = 100 * 15
    done = len(rows)
    if done > expected:
        raise RuntimeError(f"unexpected job count {done}")
    for filename in ("技术思路稿-基线.md",):
        copy(src / filename, dst / filename)
    for item in (src / "solution").glob("*.py"):
        copy(item, dst / "solution" / item.name)
    selected = {
        "README.md",
        "magis/reproduce.py", "magis/result.json", "magis/windows_compat.patch",
        "timeloop/build_native.py", "timeloop/sample_windows.cfg",
        "timeloop/timeloop-model.stats.txt", "timeloop/windows_compat.patch",
    }
    for name in selected:
        copy(src / "original_runs" / name, dst / "original_runs" / name)

    (dst / "results").mkdir(parents=True, exist_ok=True)
    fields = None
    with (dst / "results" / "summary.csv").open("w", encoding="utf-8", newline="") as fp:
        for key in sorted(rows):
            row, folder = rows[key]
            if fields is None:
                fields = list(row)
                writer = csv.DictWriter(fp, fieldnames=fields)
                writer.writeheader()
            writer.writerow(row)
            path = folder / row["case"] / f"{row['variant']}_n{row['cores']}"
            target = dst / "results" / "raw" / row["case"] / path.name
            copy(path / "result.json.gz", target / "result.json.gz")
            for plan in path.glob("*_multicore_res.json"):
                copy(plan, target / plan.name)

    metrics = src / "final_metrics"
    if done == expected and metrics.is_dir():
        for name in ("aggregate.json", "per_case_metrics.csv",
                     "mean_speedup.png", "mean_speedup.pdf"):
            copy(metrics / name, dst / "results" / name)
    snapshot = {"generated_utc": datetime.now(timezone.utc).isoformat(),
                "successful_jobs": done, "expected_jobs": expected,
                "complete": done == expected}
    (dst / "results" / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dst / "README.md").write_text(
        "# 2026 华为杯 A 题：官方评测基线\n\n"
        f"当前快照：**{done}/{expected}** 组评测成功"
        + ("，100 例已齐全。\n\n" if done == expected else "，后台仍在运行。\n\n")
        + "`solution/` 是方案生成与评测代码；`results/summary.csv` 为已完成组合的真实官方评测摘要，"
        "`results/raw/` 保留相应方案及评测返回 JSON（gzip）。完整结果时另有逐例统计和图。\n\n"
        "本仓库不包含题目原始 DOCX/ZIP、100 个输入图或两套第三方仓库源码。"
        "运行前请从比赛附件自行取得 `official/code` 与 `official/data`。"
        "评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。\n",
        encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False))


if __name__ == "__main__":
    main()
