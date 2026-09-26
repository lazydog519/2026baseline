"""Run independent cold solves, each with its own process and output directory."""
import argparse
import concurrent.futures
import csv
import json
import subprocess
import sys
import time
from pathlib import Path


def job(task):
    project, root, index, cores, search_config, resume = task
    name = f"case_{index:03d}"
    folder = root/name/f"n{cores}"
    folder.mkdir(parents=True, exist_ok=True)
    status = folder/"process.json"
    plan = folder/f"{name}_multicore_res.json"
    if resume and status.exists() and plan.exists():
        prior = json.loads(status.read_text(encoding="utf-8"))
        if prior.get("returncode") == 0 and prior.get("schema") == "q3-cold-fusion-v1":
            return prior
    command = [sys.executable, "-X", "utf8", str(project/"solution"/"q3_cold.py"),
               str(project/"official"/"data"/f"{name}.json"), "-n", str(cores),
               "--search-config", str(search_config), "--trace-dir", str(folder),
               "-o", str(plan)]
    start = time.perf_counter()
    with (folder/"console.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    report = {"case": name, "cores": cores, "returncode": result.returncode,
              "process_wall_s": time.perf_counter()-start}
    if result.returncode == 0:
        report.update(json.loads((folder/"run.json").read_text(encoding="utf-8")))
    (folder/"process.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, nargs="+", default=list(range(1, 101)))
    parser.add_argument("--cores", type=int, nargs="+", default=[2, 3, 4, 5])
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--search-config", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    project, root = args.project.resolve(), args.output.resolve()
    config = (args.search_config or project/"solution"/"q3_cold_config.json").resolve()
    root.mkdir(parents=True, exist_ok=True)
    jobs = [(project, root, case, n, config, args.resume) for case in args.cases for n in args.cores]
    # Resume only skips fully completed output jobs; each new solve reads its own graph.
    progress = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(job, task): task for task in jobs}
        failures = []
        for fut in concurrent.futures.as_completed(pending):
            r = fut.result()
            progress.append({k: r.get(k) for k in ("case", "cores", "returncode",
                             "makespan_cycles", "cache_hit_rate", "process_wall_s")})
            with (root/"progress.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(progress[0]))
                writer.writeheader()
                writer.writerows(sorted(progress, key=lambda row: (row["case"], row["cores"])))
            print(r["case"], r["cores"], r["returncode"], r.get("makespan_cycles"),
                  round(r["process_wall_s"], 2), flush=True)
            if r["returncode"]:
                failures.append([r["case"], r["cores"]])
    if failures:
        raise SystemExit(f"Failed jobs: {failures}")


if __name__ == "__main__":
    main()
