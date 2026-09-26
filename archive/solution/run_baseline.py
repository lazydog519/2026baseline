"""用赛题原始评测函数运行三问的 100 用例基线，支持中断后续跑。

本程序及代码在 OpenAI Codex（OpenAI，GPT-6）辅助下完成。模型版本发布日
当前无法核实；队员正式提交前应依比赛规定补录可核实的产品信息。
"""

import argparse
import csv
import gzip
import json
import sys
import time
import traceback
from pathlib import Path

from baseline import make_plan


HEADER = ("case", "variant", "cores", "status", "makespan_cycles",
          "original_copy_bytes", "scheduled_copy_bytes", "added_copy_bytes",
          "cache_hit_rate", "cache_hit_bytes", "wall_seconds", "error")


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8")


def run_one(graph, variant, cores, plan, settings):
    if variant == "singlecore":
        from singlecore_evaluate import evaluate_singlecore
        return evaluate_singlecore(
            graph, bandwidth=settings["bandwidth"], capacity=settings["capacity"],
            cross_core_wait=settings["a"]["task_cross_core_wait_cycles"],
            same_core_wait=settings["a"]["task_same_core_wait_cycles"])
    if variant == "q1":
        from multicore_cut_evaluate_problem_1 import evaluate_scene_a
        return evaluate_scene_a(
            graph, plan, bandwidth=settings["bandwidth"], capacity=settings["capacity"],
            cross_core_wait=settings["a"]["task_cross_core_wait_cycles"],
            same_core_wait=settings["a"]["task_same_core_wait_cycles"])
    if variant == "q2":
        from multicore_cut_evaluate_problem_2 import evaluate_scene_b
        return evaluate_scene_b(
            graph, plan, bandwidth=settings["bandwidth"], capacity=settings["capacity"],
            cross_core_copy_delay=settings["b"]["cross_core_copy_delay_cycles"])
    if variant == "q3":
        from multicore_cut_evaluate_problem_3 import evaluate_problem_3
        return evaluate_problem_3(
            graph, plan, bandwidth=settings["bandwidth"], capacity=settings["capacity"],
            cross_core_copy_delay=settings["b"]["cross_core_copy_delay_cycles"],
            **settings["cache"])
    raise ValueError(variant)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-cases", type=int, default=100)
    parser.add_argument("--start-case", type=int, default=1)
    parser.add_argument("--end-case", type=int, default=100)
    args = parser.parse_args()
    sys.path.insert(0, str(args.official / "code"))
    from evaluation_validation import read_evaluation_config
    from multicore_cut_evaluate_problem_1 import read_scene_a_config
    from multicore_cut_evaluate_problem_2 import read_scene_b_config
    from multicore_cut_evaluate_problem_3 import read_cache_config

    config_path = args.official / "data" / "config.txt"
    common = read_evaluation_config(str(config_path))
    settings = {"bandwidth": common["bandwidth"], "capacity": common["capacity"],
                "a": read_scene_a_config(str(config_path)),
                "b": read_scene_b_config(str(config_path)),
                "cache": read_cache_config(str(config_path))}
    args.output.mkdir(parents=True, exist_ok=True)
    summary = args.output / "summary.csv"
    done = set()
    if summary.exists():
        with summary.open("r", encoding="utf-8", newline="") as fp:
            done = {(row["case"], row["variant"], int(row["cores"]))
                    for row in csv.DictReader(fp) if row["status"] == "ok"}
    graphs = sorted((args.official / "data").glob("case_*.json"))[:args.max_cases]
    if len(graphs) != min(100, args.max_cases):
        raise RuntimeError(f"expected {min(100,args.max_cases)} cases, got {len(graphs)}")
    graphs = [path for path in graphs
              if args.start_case <= int(path.stem.split("_")[-1]) <= args.end_case]
    new_file = not summary.exists()
    with summary.open("a", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=HEADER)
        if new_file:
            writer.writeheader()
        for graph_path in graphs:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            plans = {n: make_plan(graph, n) for n in range(1, 6)}
            jobs = [("singlecore", 1), *(("q1", n) for n in range(2, 6)),
                    *(("q2", n) for n in range(1, 6)),
                    *(("q3", n) for n in range(1, 6))]
            for variant, cores in jobs:
                key = (graph_path.stem, variant, cores)
                if key in done:
                    continue
                path = args.output / graph_path.stem / f"{variant}_n{cores}"
                path.mkdir(parents=True, exist_ok=True)
                plan = None if variant == "singlecore" else plans[cores]
                if plan is not None:
                    save_json(path / f"{graph_path.stem}_multicore_res.json", plan)
                t0 = time.perf_counter()
                row = dict(zip(HEADER, [""] * len(HEADER)))
                row.update(case=graph_path.stem, variant=variant, cores=cores)
                try:
                    result = run_one(graph, variant, cores, plan, settings)
                    result["input_graph"] = graph_path.name
                    movement = result.get("data_movement_bytes", {})
                    cache = result.get("cache_stats", {})
                    row.update(status="ok", makespan_cycles=result["makespan"],
                               original_copy_bytes=movement.get("original_graph_copy_bytes", ""),
                               scheduled_copy_bytes=movement.get("scheduled_copy_bytes", ""),
                               added_copy_bytes=movement.get("added_copy_bytes", ""),
                               cache_hit_rate=cache.get("hit_rate", ""),
                               cache_hit_bytes=cache.get("hit_bytes", ""))
                    with gzip.open(path / "result.json.gz", "wt", encoding="utf-8",
                                   compresslevel=1) as out:
                        json.dump(result, out, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    row.update(status="error", error=traceback.format_exc()[-1200:])
                    path.mkdir(parents=True, exist_ok=True)
                    (path / "error.txt").write_text(row["error"], encoding="utf-8")
                row["wall_seconds"] = round(time.perf_counter() - t0, 3)
                writer.writerow(row)
                fp.flush()
                print(graph_path.stem, variant, cores, row["status"],
                      row["makespan_cycles"], row["wall_seconds"], flush=True)
            del graph
    print("Finished. See", summary)


if __name__ == "__main__":
    main()
