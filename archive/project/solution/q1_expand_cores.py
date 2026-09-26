"""Evaluate five-core-winning Problem 1 strategies on two to four cores."""

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    with (project / "final_metrics" / "per_case_metrics.csv").open(
            encoding="utf-8", newline="") as stream:
        baseline = {r["case"]: int(float(r["q1_cycles"]))
                    for r in csv.DictReader(stream) if r["cores"] == "5"}
    best = {}
    with (project / "q1_optimization" / "candidate_summary.csv").open(
            encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["status"] != "ok" or row["cores"] != "5":
                continue
            case = row["case"]
            if (int(row["makespan_cycles"]) < baseline[case] and
                    (case not in best or
                     int(row["makespan_cycles"]) <
                     int(best[case]["makespan_cycles"]))):
                best[case] = row
    groups = defaultdict(list)
    for case, row in best.items():
        groups[row["strategy"]].append(int(case[-3:]))
    for strategy, cases in sorted(groups.items()):
        command = [sys.executable, "-X", "utf8", "-u",
                   str(project / "solution" / "q1_search.py"),
                   "--official", str(project / "official"),
                   "--output", str(project / "q1_optimization"),
                   "--cases", *map(str, sorted(cases)),
                   "--cores", "2", "3", "4",
                   "--strategies", strategy]
        print(f"{strategy}: {len(cases)} cases", flush=True)
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
