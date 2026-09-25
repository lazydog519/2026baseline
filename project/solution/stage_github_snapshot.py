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
    for filename in ("技术思路稿-基线.md", "技术思路稿-问题一优化.md",
                     "技术思路稿-问题二优化.md", "技术思路稿-问题二独立求解.md",
                     "技术思路稿-问题一独立求解.md"):
        if (src / filename).is_file():
            copy(src / filename, dst / filename)
            if filename in ("技术思路稿-问题一独立求解.md", "技术思路稿-问题二独立求解.md"):
                report = dst / filename
                report.write_text(report.read_text(encoding="utf-8").replace(
                    "](q2_cold/", "](project/q2_cold/").replace(
                    "](q1_cold/", "](project/q1_cold/"), encoding="utf-8")
    for item in (src / "solution").glob("*.py"):
        copy(item, dst / "solution" / item.name)
    for item in (src / "solution").glob("*.json"):
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
    candidate_summary = src / "q1_optimization" / "candidate_summary.csv"
    if candidate_summary.is_file():
        with candidate_summary.open(encoding="utf-8", newline="") as fp:
            for row in csv.DictReader(fp):
                if row["status"] == "ok":
                    result = (src / "q1_optimization" / row["case"] /
                              f"n{row['cores']}" / row["strategy"] /
                              "result.json.gz")
                    if not result.is_file():
                        raise RuntimeError(f"missing candidate result: {result}")
                    complete_results.add(result.resolve())
    for summary in (src / "q2_optimization").glob("**/candidate_summary.csv"):
        with summary.open(encoding="utf-8", newline="") as fp:
            for row in csv.DictReader(fp):
                if row["status"] == "ok":
                    result = (summary.parent / row["case"] /
                              f"n{row['cores']}" / row["strategy"] /
                              "result.json.gz")
                    if not result.is_file():
                        raise RuntimeError(f"missing Q2 candidate result: {result}")
                    complete_results.add(result.resolve())
    for item in src.rglob("*"):
        if (not item.is_file() or "__pycache__" in item.parts or
                item.suffix == ".pyc" or item.name.startswith("~$")):
            continue
        if item.name == "result.json.gz" and item.resolve() not in complete_results:
            continue
        target = dst / "project" / item.relative_to(src)
        if target.exists() and target.stat().st_size == item.stat().st_size \
                and target.stat().st_mtime_ns == item.stat().st_mtime_ns:
            continue
        copy(item, target)
    for folder in src.parent.glob("A题*"):
        if folder == src or not folder.is_dir():
            continue
        for item in folder.rglob("*"):
            if (item.is_file() and "__pycache__" not in item.parts and
                    not item.name.startswith("~$")):
                copy(item, dst / "project" / "related_outputs" / folder.name /
                     item.relative_to(folder))
    if args.a_source:
        a_dir = args.a_source.resolve()
        # The extracted bundle already lives in project/official; retain its
        # original ZIP and question DOCX without another 100-case copy.
        for item in a_dir.iterdir():
            if item.is_file() and not item.name.startswith("~$"):
                copy(item, dst / "project" / "source_attachment" / "A题" /
                     item.name)
        outer_zip = a_dir.parent / "A题.zip"
        if outer_zip.is_file():
            copy(outer_zip, dst / "project" / "source_attachment" / outer_zip.name)

    metrics = src / "final_metrics"
    if done == expected and metrics.is_dir():
        for name in ("aggregate.json", "per_case_metrics.csv", "verification.json",
                     "mean_speedup.png", "mean_speedup.pdf"):
            copy(metrics / name, dst / "results" / name)
    snapshot = {"generated_utc": datetime.now(timezone.utc).isoformat(),
                "successful_jobs": done, "expected_jobs": expected,
                "complete": done == expected}
    q1_final = src / "q1_optimization" / "final" / "aggregate.json"
    if q1_final.is_file():
        q1_metrics = json.loads(q1_final.read_text(encoding="utf-8"))
        q1_complete = (q1_metrics["complete_cases"] == 100 and
                       q1_metrics["missing_jobs"] == 0 and
                       q1_metrics["evaluated_selections"] == 400)
        snapshot["q1_complete"] = q1_complete
        snapshot["q1_five_core_mean_speedup"] = q1_metrics[
            "arithmetic_mean_speedup"]["5"]
        snapshot["complete"] &= q1_complete
    q2_final = src / "q2_optimization" / "final" / "aggregate.json"
    if q2_final.is_file():
        for name in ("aggregate.json", "per_case_metrics.csv",
                     "mean_speedup.png", "mean_speedup.pdf"):
            copy(q2_final.parent / name, dst / "results" / "q2_optimized" / name)
        q2_metrics = json.loads(q2_final.read_text(encoding="utf-8"))
        (dst / "results" / "q2_optimized" / "README.md").write_text(
            "# 历史离线选优\n\n本目录属于旧的多轮离线实验，不能代表当前独立求解算法。"
            "当前统一预算、独立启动结果见 ../q2_cold/，并以其 aggregate.json 中的复核状态为准。\n",
            encoding="utf-8")
        q2_complete = (q2_metrics["complete_cases"] == 100 and
                       q2_metrics["missing_jobs"] == 0 and
                       q2_metrics["evaluated_selections"] == 400 and
                       q2_metrics["official_recheck"])
        snapshot["q2_complete"] = q2_complete
        snapshot["q2_five_core_mean_speedup"] = q2_metrics[
            "arithmetic_mean_speedup"]["5"]
        snapshot["complete"] &= q2_complete
    q2_cold = src / "q2_cold" / "final" / "aggregate.json"
    if q2_cold.is_file():
        cold = json.loads(q2_cold.read_text(encoding="utf-8"))
        cold_complete = (cold["complete_cases"] == 100 and cold["missing_jobs"] == 0
                         and cold["rechecked_jobs"] == 400 and cold["cold_start"])
        snapshot["q2_historical_selection_complete"] = snapshot.get("q2_complete", False)
        snapshot["q2_complete"] = cold_complete
        snapshot["q2_cold_start"] = True
        snapshot["q2_five_core_mean_speedup"] = cold["arithmetic_mean_speedup"]["5"]
        snapshot["complete"] = done == expected and snapshot.get("q1_complete", True) and cold_complete
        for item in q2_cold.parent.iterdir():
            if item.is_file():
                copy(item, dst / "results" / "q2_cold" / item.name)
    q1_cold = src / "q1_cold" / "final" / "aggregate.json"
    if q1_cold.is_file():
        cold = json.loads(q1_cold.read_text(encoding="utf-8"))
        cold_complete = (cold["complete_cases"] == 100 and cold["missing_jobs"] == 0
                         and cold["rechecked_jobs"] == 400 and cold["cold_start"])
        snapshot["q1_historical_selection_complete"] = snapshot.get("q1_complete", False)
        snapshot["q1_complete"] = cold_complete
        snapshot["q1_cold_start"] = True
        snapshot["q1_five_core_mean_speedup"] = cold["arithmetic_mean_speedup"]["5"]
        snapshot["complete"] = done == expected and snapshot.get("q2_complete", True) and cold_complete
        for item in q1_cold.parent.iterdir():
            if item.is_file():copy(item, dst / "results" / "q1_cold" / item.name)
    (dst / "results" / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    q1_text = ("\n问题一优化：见 [`技术思路稿-问题一优化.md`](技术思路稿-问题一优化.md)、"
               "[`project/q1_optimization/final/`](project/q1_optimization/final/) "
               "和 [`project/solution/q1_submit.py`](project/solution/q1_submit.py)。"
               f"5 核逐例平均加速比为 **{snapshot['q1_five_core_mean_speedup']:.6f}**。\n"
               if "q1_five_core_mean_speedup" in snapshot else "")
    if snapshot.get("q1_cold_start"):
        q1_text = ("\n问题一当前提交版：从输入图独立求解，固定最多六次官方评估，不读取历史方案。见 "
                   "[`技术思路稿-问题一独立求解.md`](技术思路稿-问题一独立求解.md)、"
                   "[`results/q1_cold/`](results/q1_cold/)、"
                   "[`论文公式`](project/q1_cold/模型与算法公式.tex) 和 "
                   "[`独立代码包`](project/q1_cold/submission_q1.zip)。"
                   f"100 例 5 核平均加速比 **{snapshot['q1_five_core_mean_speedup']:.6f}**。"
                   "400 份最终方案已由原评估器逐份重新核验。\n\n"
                   "运行入口：`python project/solution/q1_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。"
                   "旧 `q1_optimization/` 为历史离线选优，不作为当前独立求解成绩。\n")
    q2_text = ("\n问题二优化：见 [`技术思路稿-问题二优化.md`](技术思路稿-问题二优化.md)、"
               "[`project/q2_optimization/final/`](project/q2_optimization/final/) "
               "和 [`project/solution/q2_submit.py`](project/solution/q2_submit.py)。"
               f"5 核逐例平均加速比为 **{snapshot['q2_five_core_mean_speedup']:.6f}**。\n"
               if "q2_five_core_mean_speedup" in snapshot else "")
    if snapshot.get("q2_cold_start"):
        q2_text = ("\n问题二当前提交版：从输入图独立求解，不读取历史方案。见 "
                   "[`技术思路稿-问题二独立求解.md`](技术思路稿-问题二独立求解.md)、"
                   "[`results/q2_cold/`](results/q2_cold/) 和 "
                   "[`独立代码包`](project/q2_cold/submission_q2.zip)。"
                   f"100 例 5 核平均加速比 **{snapshot['q2_five_core_mean_speedup']:.6f}**。"
                   "400 份最终方案已由原评估器重新核验。\n\n"
                   "运行入口：`python project/solution/q2_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。"
                   "旧 `q2_optimization/` 为不同预算的历史离线实验，不作为当前独立求解成绩。"
                   "\n")
    (dst / "README.md").write_text(
        "# 2026 官方基线与问题一、二优化\n\n"
        f"当前快照：**{done}/{expected}** 组评测成功"
        + ("，100 例已齐全。\n\n" if done == expected else "，后台仍在运行。\n\n")
        + "`solution/` 是方案生成与评测代码；`results/summary.csv` 为已完成组合的真实官方评测摘要，"
        "`results/raw/` 保留相应方案及评测返回 JSON（gzip）。完整结果时另有逐例统计和图。\n\n"
        "`project/` 保存 A 题项目目录的完整快照，`project/source_attachment/` 保存原始 A 题 DOCX/ZIP，"
        "`project/related_outputs/` 保存此前的 A 题导读和开源复用评估；"
        "不包含其他赛题和两套第三方仓库源码。运行中的结果仅在官方评测写入成功状态后复制。"
        "评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。\n"
        + q1_text + q2_text,
        encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False))


if __name__ == "__main__":
    main()
