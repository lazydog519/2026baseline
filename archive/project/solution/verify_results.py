"""复核 1500 份评测返回与 1400 份方案文件的完整性。"""

import argparse
import csv
import gzip
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    jobs = {}
    for folder in args.inputs:
        with (folder / "summary.csv").open(encoding="utf-8", newline="") as fp:
            for row in csv.DictReader(fp):
                if row["status"] == "ok":
                    jobs[(row["case"], row["variant"], int(row["cores"]))] = (folder, row)
    errors = []
    if len(jobs) != 1500:
        errors.append(f"expected 1500 distinct successful jobs; found {len(jobs)}")
    graph_ops = {}
    results_checked = plans_checked = 0
    for (case, variant, cores), (folder, row) in sorted(jobs.items()):
        base = folder / case / f"{variant}_n{cores}"
        try:
            with gzip.open(base / "result.json.gz", "rt", encoding="utf-8") as fp:
                result = json.load(fp)
            if result["makespan"] != int(row["makespan_cycles"]):
                raise ValueError("makespan differs from summary.csv")
            if result["input_graph"] != case + ".json":
                raise ValueError("input graph label differs")
            results_checked += 1
            if variant != "singlecore":
                plan = json.loads((base / f"{case}_multicore_res.json").read_text(encoding="utf-8"))
                if case not in graph_ops:
                    graph = json.loads((args.official / "data" / (case + ".json")).read_text(encoding="utf-8"))
                    graph_ops[case] = {str(op["id"]) for op in graph["ops"]
                                       if op["op"] not in ("COPY_IN", "COPY_OUT")}
                if set(plan["node_to_subgraph"]) != graph_ops[case]:
                    raise ValueError("plan omits or adds compute operation IDs")
                if len(plan["core_schedules"]) != cores:
                    raise ValueError("core_schedules length differs")
                plans_checked += 1
        except Exception as exc:
            errors.append(f"{case} {variant} n{cores}: {exc}")
    report = {"results_checked": results_checked, "plans_checked": plans_checked,
              "errors": errors[:20], "error_count": len(errors)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
