"""Two restrained, data-linked figures for the seven-case pilot."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

HERE = Path(__file__).resolve().parent
OUT = HERE / "figures"
OUT.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "font.size": 10.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "pdf.fonttype": 42,
})
BLUE, ORANGE = "#245677", "#B65E30"
RED, GREEN, INK = "#B64742", "#287F69", "#263640"


def export(fig, name):
    for suffix in ("png", "pdf"):
        fig.savefig(OUT / f"{name}.{suffix}", dpi=260, bbox_inches="tight",
                    facecolor="white")
    plt.close(fig)


def reductions():
    data = list(csv.DictReader((HERE / "branch_validation/paired_reductions.csv").open(
        encoding="utf-8", newline="")))
    order = ["case_005", "case_044", "case_071", "case_074", "case_082",
             "case_069", "case_086"]
    fig, ax = plt.subplots(figsize=(8.2, 4.5), constrained_layout=True)
    jitter = {17: -0.14, 29: 0, 43: 0.14}
    for row, case in enumerate(order):
        items = [r for r in data if r["case"] == case]
        xs = [float(r["reduction_percent"]) for r in items]
        colour = BLUE if items[0]["role"] == "development" else ORANGE
        ax.plot([min(xs), max(xs)], [row, row], lw=1.1, color=colour, alpha=.50)
        for item in items:
            ax.scatter(float(item["reduction_percent"]),
                       row + jitter[int(item["seed"])], s=24,
                       facecolors="white", edgecolors=colour, linewidths=1.25,
                       zorder=3)
        mean = sum(xs) / len(xs)
        ax.scatter(mean, row, s=58, marker="D", color=colour, zorder=4)
        ax.text(max(xs) + 1.8, row, f"{mean:.1f}%", va="center",
                fontsize=9.4, color=INK)
    ax.axvline(0, color="#8D969A", lw=.85)
    ax.axhline(4.5, color="#D6DADB", lw=.8)
    ax.set_yticks(range(len(order)), [c[-3:] for c in order])
    ax.invert_yaxis()
    ax.set_xlim(-4, 73)
    ax.set_xlabel("相同 30 次官方评测预算下的完成时间缩短率（%）")
    ax.set_ylabel("算例")
    ax.grid(axis="x", color="#E7EAEB", lw=.65)
    ax.set_axisbelow(True)
    ax.text(0.02, .02, "蓝色：5 个开发样本  ·  橙色：069、086 算子冻结后验证",
            transform=ax.transAxes, fontsize=8.7, color="#59666D")
    ax.set_title("分支分离算子的配对效果", loc="left", weight="bold",
                 color=INK, pad=12)
    ax.legend(handles=[
        Line2D([0], [0], marker="D", linestyle="None", color=BLUE,
               label="开发样本均值", markersize=6),
        Line2D([0], [0], marker="D", linestyle="None", color=ORANGE,
               label="验证样本均值", markersize=6),
        Line2D([0], [0], marker="o", linestyle="None", markerfacecolor="white",
               markeredgecolor=INK, label="单个随机种子", markersize=5)],
        frameon=False, loc="lower right", fontsize=8.4)
    export(fig, "paired_reduction")


def fifo_event():
    item = json.loads((HERE / "branch_validation/mechanism.json").read_text(
        encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(8.8, 3.7), constrained_layout=True)
    labels = [(1, "分离前", item["parent"]),
              (0, "分离后", item["child"])]
    for y, label, trial in labels:
        ev = trial["tensor_events"]
        misses = [x for x in ev if x["event"] == "miss"]
        hits = [x for x in ev if x["event"] == "hit"]
        fills = [x for x in ev if x["event"] == "insert"]
        first = min(x["time"] for x in misses)
        fill = min(x["time"] for x in fills)
        ax.axvspan(first, fill, ymin=(y + .15) / 2, ymax=(y + .50) / 2,
                   color="#DCE9F2", alpha=.75, lw=0)
        ax.plot([first, max(x["time"] for x in ev)], [y, y],
                color="#A8B1B6", lw=1, zorder=1)
        shown = []
        for event in misses + hits:
            colour = RED if event["event"] == "miss" else GREEN
            marker = "x" if event["event"] == "miss" else "o"
            x = event["time"]
            ax.scatter(x, y, c=colour, marker=marker, s=56, linewidths=1.8,
                       zorder=3)
            close = any(abs(x - earlier) < 145 for earlier in shown)
            offset = .25 if close else .13
            ax.text(x + (115 if close else 0),
                    y + offset if y == 1 else y - offset,
                    f"C{event['core']}", ha="center",
                    va="bottom" if y == 1 else "top", fontsize=8.5,
                    color=colour)
            shown.append(x)
        ax.vlines(fill, y - .26, y + .29, colors=BLUE, lw=1.6, zorder=2)
        ax.text(fill + 65, y - .25 if y == 1 else y + .23, f"填充 {fill}",
                fontsize=8.8, color=BLUE,
                va="top" if y == 1 else "bottom")
        ax.text(11900, y + .29, f"总时间 {trial['makespan']:,} 周期",
                ha="right", va="bottom", color=INK, fontsize=9.4)
    ax.set_xlim(6800, 12100)
    ax.set_ylim(-.48, 1.55)
    ax.set_yticks([0, 1], ["分离后", "分离前"])
    ax.set_xlabel("张量读取与 L2 填充的实际事件时刻（周期）")
    ax.grid(axis="x", color="#E7EAEB", lw=.65)
    ax.set_axisbelow(True)
    ax.set_title("同一张量的首次填充窗口决定后续读取路径",
                 loc="left", weight="bold", color=INK, pad=10)
    ax.text(.01, -.29, "case_044，张量 1000000049（73,728 B）；同一冷启动搜索中的一次分支分离",
            transform=ax.transAxes, fontsize=8.7, color="#59666D")
    ax.legend(handles=[
        Line2D([0], [0], marker="x", color=RED, linestyle="None",
               label="DDR 未命中", markersize=7),
        Line2D([0], [0], marker="o", color=GREEN, linestyle="None",
               label="L2 命中", markersize=6),
        Line2D([0], [0], color=BLUE, lw=1.6, label="首次填充")],
        frameon=False, loc="upper left", ncol=3, fontsize=8.5)
    export(fig, "fifo_window_case044")


if __name__ == "__main__":
    reductions()
    fifo_event()
