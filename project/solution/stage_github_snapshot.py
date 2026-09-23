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
    parser.add_argument("--a-source", type=Path,
                        help="原题 A 题目录；连同其上级的 A题.zip 一起归档")
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

    # 用户要求保存 A 题项目的全部内容。运行中的 gzip 尚未写完，等其 ok 行落盘再复制。
    complete_results = {
        (folder / row["case"] / f"{row['variant']}_n{row['cores']}" / "result.json.gz").resolve()
        for row, folder in rows.values()
    }
    for item in src.rglob("*"):
        if not item.is_file() or "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        if item.name == "result.json.gz" and item.resolve() not in complete_results:
            continue
        target = dst / "project" / item.relative_to(src)
        if target.exists() and target.stat().st_size == item.stat().st_size \
                and target.stat().st_mtime_ns == item.stat().st_mtime_ns:
            continue
        copy(item, target)
    if args.a_source:
        a_dir = args.a_source.resolve()
        for item in a_dir.rglob("*"):
            if item.is_file():
                copy(item, dst / "project" / "source_attachment" / "A题" /
                     item.relative_to(a_dir))
        outer_zip = a_dir.parent / "A题.zip"
        if outer_zip.is_file():
            copy(outer_zip, dst / "project" / "source_attachment" / outer_zip.name)

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
        "`project/` 保存 A 题项目目录的完整快照，`project/source_attachment/` 保存原始 A 题 DOCX/ZIP；"
        "不包含其他赛题和两套第三方仓库源码。运行中的结果仅在官方评测写入成功状态后复制。"
        "评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。\n",
        encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False))


if __name__ == "__main__":
    main()
