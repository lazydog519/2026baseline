"""Recompute compact paper tables from the independently audited pilot CSV."""
import csv
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
IN = HERE / "branch_validation/metrics.csv"
OUT = HERE / "branch_validation"


def main():
    rows = list(csv.DictReader(IN.open(encoding="utf-8", newline="")))
    assert len(rows) == 42
    records = []
    paired = []
    for case in sorted({r["case"] for r in rows}):
        a = sorted((r for r in rows if r["case"] == case and r["variant"] == "prior"),
                   key=lambda r: int(r["seed"]))
        b = sorted((r for r in rows if r["case"] == case and r["variant"] == "branch"),
                   key=lambda r: int(r["seed"]))
        assert [r["seed"] for r in a] == [r["seed"] for r in b] == ["17", "29", "43"]
        def avg(group, key):
            return statistics.mean(float(r[key]) for r in group)
        pair = [dict(seed=int(x["seed"]), prior=int(x["makespan"]),
                     branch=int(y["makespan"]),
                     reduction_percent=100 * (int(x["makespan"]) - int(y["makespan"]))
                     / int(x["makespan"])) for x, y in zip(a, b)]
        paired.extend(dict(role=a[0]["role"], case=case, **r) for r in pair)
        prior, branch = avg(a, "makespan"), avg(b, "makespan")
        records.append(dict(case=case, role=a[0]["role"],
                            prior_mean_cycles=prior,
                            branch_mean_cycles=branch,
                            reduction_of_means_percent=100 * (prior - branch) / prior,
                            mean_paired_reduction_percent=statistics.mean(
                                p["reduction_percent"] for p in pair),
                            prior_added_copy_bytes=avg(a, "added_copy_bytes"),
                            branch_added_copy_bytes=avg(b, "added_copy_bytes"),
                            prior_cache_miss_bytes=avg(a, "cache_miss_bytes"),
                            branch_cache_miss_bytes=avg(b, "cache_miss_bytes"),
                            branch_same_plan_l2_ratio=statistics.mean(
                                float(r["no_l2_same_plan"]) / float(r["makespan"])
                                for r in b),
                            branch_min_cycles=min(int(r["makespan"]) for r in b),
                            branch_max_cycles=max(int(r["makespan"]) for r in b),
                            paired_wins=sum(p["branch"] < p["prior"] for p in pair),
                            paired_ties=sum(p["branch"] == p["prior"] for p in pair)))
    summary = dict(scope="7 selected cases x 3 fixed seeds x 2 methods, 5 cores only",
                   official_budget_per_search=30, cases=records,
                   mean_paired_reduction_percent=statistics.mean(
                       p["reduction_percent"] for p in paired),
                   development_mean_paired_reduction_percent=statistics.mean(
                       p["reduction_percent"] for p in paired if p["role"] == "development"),
                   algorithm_holdout_mean_paired_reduction_percent=statistics.mean(
                       p["reduction_percent"] for p in paired if p["role"] == "algorithm_holdout"),
                   wins=sum(p["branch"] < p["prior"] for p in paired),
                   ties=sum(p["branch"] == p["prior"] for p in paired),
                   losses=sum(p["branch"] > p["prior"] for p in paired),
                   disclaimer="Selected-sample evidence, not a 100-case score or a guarantee of generalization.")
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)
                                      + "\n", encoding="utf-8")
    with (OUT / "case_summary.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    with (OUT / "paired_reductions.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(paired[0]))
        w.writeheader()
        w.writerows(paired)
    print(json.dumps({k: summary[k] for k in ("mean_paired_reduction_percent",
                                                "wins", "ties", "losses")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
