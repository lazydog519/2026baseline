"""Two publication-sized figures drawn only from independently audited Q3 data."""
import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    audit = project / "q3_cold" / "final"
    summary = json.loads((audit / "aggregate.json").read_text(encoding="utf-8"))
    assert summary["complete_cases"] == 100 and summary["rechecked_jobs"] == 500
    with (audit / "audit_progress.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 500
    out = project / "q3_cold" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.8, "font.size": 10,
        "savefig.dpi": 240, "pdf.fonttype": 42,
    })
    blue, orange, gray = "#235578", "#B46E4E", "#68747D"
    n = np.arange(1, 6)
    l2 = np.array([np.mean([float(r["speedup_vs_reference"]) for r in rows
                            if int(r["cores"]) == k]) for k in n])
    same_no_l2 = np.array([np.mean([float(r["singlecore_reference_cycles"]) /
                                    float(r["same_plan_no_l2_cycles"]) for r in rows
                                    if int(r["cores"]) == k]) for k in n])
    fig, ax = plt.subplots(figsize=(6.8, 4.2), constrained_layout=True)
    ax.plot(n, same_no_l2, "o-", color=gray, lw=1.8, markersize=5,
            label="同一方案，无 L2")
    ax.plot(n, l2, "o-", color=blue, lw=2.2, markersize=5.5,
            label="同一方案，启用 FIFO L2")
    q2 = summary["q2_five_core_comparison"]
    ax.plot([5], [q2], marker="D", markersize=5.5, color=orange,
            linestyle="none", label="问题二独立求解（5 核）")
    ax.annotate(f"{l2[-1]:.3f}", (5, l2[-1]), xytext=(-28, 12),
                textcoords="offset points", color=blue)
    ax.set(xlim=(0.8, 5.2), xticks=n, xlabel="核数", ylabel="100 例逐例算术平均加速比")
    ax.set_ylim(bottom=0.8)
    ax.grid(axis="y", color="#E6EAED", lw=0.7)
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    for suffix in ("png", "pdf"):
        fig.savefig(out / f"five_core_scaling.{suffix}")
    plt.close(fig)

    five = [r for r in rows if int(r["cores"]) == 5]
    gains = np.array([float(r["same_plan_l2_gain"]) for r in five])
    sources = [project / "q3_cold" / "full5" / "case_044" / "n5" /
               "official_result.json.gz",
               project / "q3_cold" / "fusion_full" / "case_044" / "n5" /
               "result.json.gz"]
    with gzip.open(sources[0], "rt", encoding="utf-8") as stream:
        before = json.load(stream)
    with gzip.open(sources[1], "rt", encoding="utf-8") as stream:
        after = json.load(stream)
    def hit_bytes(result):
        return Counter({e["tensor_id"]: sum(x["size_bytes"] for x in result["cache_events"]
                                            if x["tensor_id"] == e["tensor_id"] and
                                            x["event"] == "hit")
                        for e in result["cache_events"]})
    old_hits, new_hits = hit_bytes(before), hit_bytes(after)
    tensor = min(new_hits, key=lambda t: (-(new_hits[t] - old_hits[t]), t))
    panels = [[e for e in result["cache_events"] if e["tensor_id"] == tensor and
               e["event"] in ("miss", "hit", "insert")]
              for result in (before, after)]
    times = [e["time"] for panel in panels for e in panel]
    fig, axes = plt.subplots(2, 1, figsize=(7.0, 4.7), sharex=True,
                             constrained_layout=True)
    for ax, events, title, result in zip(
            axes, panels, ("阶段一候选", "融合后最终方案"), (before, after)):
        for event, color, marker in (("miss", orange, "x"), ("hit", blue, "o")):
            chosen = [e for e in events if e["event"] == event]
            if chosen:
                ax.scatter([e["time"] for e in chosen],
                           [e["core_id"] for e in chosen], s=42,
                           color=color, marker=marker, zorder=3)
        for e in events:
            if e["event"] == "insert":
                ax.axvline(e["time"], color="#3A7A68", lw=1.4, ls="--")
        miss = sum(e["event"] == "miss" for e in events)
        hits = sum(e["event"] == "hit" for e in events)
        ax.set_title(f"{title}   |   DDR 未命中 {miss} 次 · L2 命中 {hits} 次 · 总时间 {result['makespan']:,} 周期",
                     loc="left", fontsize=10)
        ax.set(yticks=range(5), ylabel="核编号", ylim=(-0.5, 4.5))
        ax.grid(axis="x", color="#E6EAED", lw=0.7)
    axes[1].set(xlabel="此张量的缓存事件时刻（周期）",
                xlim=(min(times) - 250, max(times) + 250))
    legend = [Line2D([], [], color=orange, marker="x", linestyle="none", label="DDR 未命中"),
              Line2D([], [], color=blue, marker="o", linestyle="none", label="L2 命中"),
              Line2D([], [], color="#3A7A68", linestyle="--", label="填充完成")]
    axes[0].legend(handles=legend, ncol=3, loc="upper right", frameon=False,
                   fontsize=8.5)
    fig.suptitle(f"case 044 · 张量 {tensor}（{panels[1][0]['size_bytes']:,} B）",
                 x=0.06, ha="left", fontsize=11)
    for suffix in ("png", "pdf"):
        fig.savefig(out / f"fifo_event_case044.{suffix}")
    plt.close(fig)
    print(json.dumps(dict(five_core_mean=float(l2[-1]),
                          same_plan_no_l2_mean=float(same_no_l2[-1]),
                          cache_gain_median=float(np.median(gains)),
                          cache_helped_cases=int(np.count_nonzero(gains > 1.0)))), flush=True)


if __name__ == "__main__":
    main()
