"""Chapter 6 figures from the frozen Scene A/B official result tables."""
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
OUT = ROOT / "figures"
BLUE = "#245F78"
ORANGE = "#B86642"
INK = "#24343D"
MUTED = "#62737C"
GRID = "#DFE6E9"
PAPER = "#F7FAFB"
MIB = 1048576


def load(name, path):
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    keys = [(r["case"], int(r["cores"])) for r in rows]
    expected = {(f"case_{i:03d}", n) for i in range(1, 101) for n in range(2, 6)}
    if len(rows) != 400 or set(keys) != expected or len(set(keys)) != 400:
        raise ValueError(f"{name}: 100 × 4 distinct jobs required")
    if any(r["status"] != "ok" for r in rows):
        raise ValueError(f"{name}: incomplete official results")
    return {(r["case"], int(r["cores"])): r for r in rows}


def save(fig, stem):
    OUT.mkdir(exist_ok=True)
    for ext, kwargs in (("png", {"dpi": 400}), ("pdf", {}), ("svg", {})):
        fig.savefig(OUT / f"{stem}.{ext}", bbox_inches="tight",
                    facecolor="white", **kwargs)
    plt.close(fig)


def panel_box(ax, x, y, w, h, label, edge=GRID, fill="white", size=8.2):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.09,rounding_size=0.12",
        linewidth=1, edgecolor=edge, facecolor=fill))
    ax.text(x + w/2, y + h/2, label, ha="center", va="center",
            color=INK, fontsize=size, linespacing=1.55)


def arrow(ax, x0, y0, x1, y1, color=MUTED):
    ax.add_patch(FancyArrowPatch(
        (x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=11,
        linewidth=1.25, color=color, shrinkA=0, shrinkB=0))


def mechanism():
    fig, ax = plt.subplots(figsize=(7.25, 4.65))
    ax.set(xlim=(0, 10), ylim=(0, 6))
    ax.axis("off")
    for y, h in ((3.85, 1.98), (1.69, 1.98), (0.17, 1.33)):
        ax.add_patch(FancyBboxPatch(
            (0.1, y), 9.8, h, boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=0.75, edgecolor=GRID, facecolor=PAPER))

    ax.text(0.36, 5.48, "a  场景 A｜每个子图独立构成 Task",
            color=BLUE, weight="bold", fontsize=9)
    panel_box(ax, 0.48, 4.40, 2.20, 0.65, "核 0 · Task 1\n子图 $s_1$", BLUE, "#EAF2F5")
    panel_box(ax, 3.72, 4.40, 2.43, 0.65, "共享 DDR\nCOPY_OUT / COPY_IN", MUTED, "white")
    panel_box(ax, 7.22, 4.40, 2.20, 0.65, "核 0 · Task 2\n子图 $s_2$", BLUE, "#EAF2F5")
    arrow(ax, 2.79, 4.72, 3.59, 4.72)
    arrow(ax, 6.26, 4.72, 7.09, 4.72)
    ax.text(0.48, 4.02,
            "同核边仍经 DDR；切换 Task 时清空 L1/UB。相邻同核 Task 等待 100 cycle；跨核前驱等待 1000 cycle。",
            fontsize=7.5, color=MUTED)

    ax.text(0.36, 3.31, "b  场景 B｜同核子图合并为单一 Task",
            color=ORANGE, weight="bold", fontsize=9)
    panel_box(ax, 0.48, 2.25, 3.05, 0.65,
              "核 0 · 单一 Task\n子图 $s_1$ → 子图 $s_2$（片上复用）",
              ORANGE, "#F8EEE9", 7.9)
    panel_box(ax, 4.28, 2.25, 2.05, 0.65,
              "共享 DDR\n跨核 COPY_OUT / IN", MUTED, "white", 7.9)
    panel_box(ax, 7.22, 2.25, 2.20, 0.65,
              "核 1 · 单一 Task\n子图 $s_3$", ORANGE, "#F8EEE9")
    arrow(ax, 3.63, 2.57, 4.16, 2.57)
    arrow(ax, 6.44, 2.57, 7.09, 2.57)
    ax.text(0.48, 1.86,
            "同核数据驻留 L1/UB；跨核 COPY_IN 须待源 COPY_OUT 完成并经过 500 cycle 同步延迟。",
            fontsize=7.6, color=MUTED)

    ax.text(0.36, 1.21, "c  需访问 DDR 的 COPY 如何争用带宽（规则示意）",
            color=INK, weight="bold", fontsize=8.6)
    panel_box(ax, 0.46, 0.44, 2.62, 0.46, "依赖 / 顺序 / 同步条件满足", size=7.7)
    panel_box(ax, 3.65, 0.40, 2.56, 0.56,
              "核 0 / 核 1 / … COPY 就绪\n共享带宽前等待", size=7.1)
    panel_box(ax, 6.78, 0.44, 2.66, 0.46, "DDR 共享 60 byte/cycle", BLUE, "#EAF2F5", 7.8)
    arrow(ax, 3.17, 0.67, 3.53, 0.67)
    arrow(ax, 6.30, 0.67, 6.67, 0.67)
    ax.text(9.78, 1.19, "每核私有 L1 512 KiB、UB 128 KiB",
            ha="right", color=MUTED, fontsize=7.1)
    save(fig, "图6-1_场景与资源机制")


def main():
    a = load("A", PROJECT / "q1_priority_20260926/full_metrics.csv")
    b = load("B", PROJECT / "q2_priority_20260926/final_v2/full_metrics.csv")
    OUT.mkdir(exist_ok=True)
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "Arial", "DejaVu Sans"],
        "font.size": 8.5, "axes.labelsize": 9, "axes.titlesize": 9,
        "pdf.fonttype": 42, "svg.fonttype": "none",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.8, "axes.unicode_minus": False,
        "legend.frameon": False,
    })
    mechanism()

    with (OUT / "图6-2至6-4_逐例源数据.csv").open(
            "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case", "scene", "cores", "speedup", "makespan_cycles",
                         "added_copy_bytes", "spill_added_copy_bytes",
                         "other_added_copy_bytes"])
        for scene, data in (("A", a), ("B", b)):
            for case, n in sorted(data):
                r = data[case, n]
                total = int(r["added_copy_bytes"])
                spill = int(r["spill_added_copy_bytes"])
                if not 0 <= spill <= total:
                    raise ValueError(f"invalid extra-byte decomposition: {scene}/{case}/{n}")
                writer.writerow([case, scene, n, r["speedup"], r["makespan_cycles"],
                                 total, spill, total-spill])

    ns = [1, 2, 3, 4, 5]
    summary = {}
    for scene, data in (("A", a), ("B", b)):
        summary[scene] = {}
        for n in (2, 3, 4, 5):
            rs = [data[f"case_{i:03d}", n] for i in range(1, 101)]
            speeds = [float(r["speedup"]) for r in rs]
            summary[scene][str(n)] = {
                "mean_speedup": statistics.mean(speeds),
                "median_speedup": statistics.median(speeds),
                "q1_speedup": float(np.percentile(speeds, 25)),
                "q3_speedup": float(np.percentile(speeds, 75)),
                "mean_added_mib": statistics.mean(int(r["added_copy_bytes"]) for r in rs)/MIB,
                "mean_spill_mib": statistics.mean(int(r["spill_added_copy_bytes"]) for r in rs)/MIB,
            }
    (OUT / "图6-2至6-4_统计摘要.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    fig, ax = plt.subplots(figsize=(6.65, 3.45), layout="constrained")
    for scene, color, marker, label in (("A", BLUE, "o", "场景 A"),
                                         ("B", ORANGE, "s", "场景 B")):
        means = [1.0] + [summary[scene][str(n)]["mean_speedup"] for n in ns[1:]]
        ax.plot(ns, means, color=color, marker=marker, lw=1.9, ms=5.2, label=label)
        ax.annotate(f"{means[-1]:.3f}", (5, means[-1]),
                    xytext=(0, -14 if scene == "A" else 9),
                    textcoords="offset points", ha="center", color=color, fontsize=8)
    ax.set(xlim=(0.8, 5.2), ylim=(0.8, 4.35), xticks=ns,
           xlabel="AI 核数", ylabel="100 图平均加速比")
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left")
    ax.text(0.98, 0.06, "单核按题意取 1；每核数 n = 100 图",
            transform=ax.transAxes, ha="right", color=MUTED, fontsize=7.3)
    save(fig, "图6-2_两场景平均加速比")

    fig, ax = plt.subplots(figsize=(6.65, 3.55), layout="constrained")
    x = np.arange(4)
    width = 0.34
    for scene, color, shift in (("A", BLUE, -width/2), ("B", ORANGE, width/2)):
        totals = [summary[scene][str(n)]["mean_added_mib"] for n in ns[1:]]
        spills = [summary[scene][str(n)]["mean_spill_mib"] for n in ns[1:]]
        other = [t-s for t, s in zip(totals, spills)]
        ax.bar(x+shift, other, width, color=color, edgecolor=color, lw=0.8)
        ax.bar(x+shift, spills, width, bottom=other, color="white",
               edgecolor=color, hatch="///", lw=0.9)
        for xx, total in zip(x+shift, totals):
            ax.annotate(f"{total:.1f}", (xx, total), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=7.2, color=color)
    ax.set(xticks=x, xticklabels=[str(n) for n in ns[1:]],
           xlabel="AI 核数", ylabel="平均额外 DDR 搬运（MiB）")
    ax.set_ylim(0, 19.7)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    ax.legend(handles=[
        Patch(facecolor=BLUE, edgecolor=BLUE, label="场景 A"),
        Patch(facecolor=ORANGE, edgecolor=ORANGE, label="场景 B"),
        Patch(facecolor="white", edgecolor=MUTED, hatch="///",
              label="上段斜线：缓存换入/换出产生的新增搬运")
    ], loc="upper left", fontsize=7.4)
    save(fig, "图6-3_额外DDR搬运分解")

    fig, ax = plt.subplots(figsize=(6.65, 3.65), layout="constrained")
    for scene, color, offset in (("A", BLUE, -0.19), ("B", ORANGE, 0.19)):
        data = [[float((a if scene == "A" else b)[f"case_{i:03d}", n]["speedup"])
                 for i in range(1, 101)] for n in ns[1:]]
        positions = np.arange(2, 6) + offset
        bp = ax.boxplot(data, positions=positions, widths=0.29,
                        patch_artist=True, whis=1.5, showfliers=True,
                        manage_ticks=False)
        for box in bp["boxes"]:
            box.set(facecolor=color, edgecolor=color, alpha=0.22, linewidth=1)
        for median in bp["medians"]:
            median.set(color=color, linewidth=1.8)
        for whisker, cap in zip(bp["whiskers"], bp["caps"]):
            whisker.set(color=color, linewidth=0.9)
            cap.set(color=color, linewidth=0.9)
        for flier in bp["fliers"]:
            flier.set(marker="o", markersize=2.5, markerfacecolor=color,
                      markeredgecolor=color, alpha=0.65)
    ax.set(xlim=(1.55, 5.45), xticks=[2, 3, 4, 5],
           xlabel="AI 核数", ylabel="逐图加速比")
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    ax.legend(handles=[
        Patch(facecolor=BLUE, edgecolor=BLUE, alpha=0.45, label="场景 A"),
        Patch(facecolor=ORANGE, edgecolor=ORANGE, alpha=0.45, label="场景 B")
    ], loc="upper left")
    save(fig, "图6-4_逐图加速比分布")

    (OUT / "图6-1至6-4_图注.md").write_text(
        "图 6-1  规则示意图。场景 A 同核跨子图仍访问 DDR，场景 B 同核子图合并后"
        "可保留 L1/UB 数据；底部示意多个核的 COPY 请求在就绪后争用共享 DDR 总带宽。"
        "箭头不代表实测时长，也不指定请求的 FIFO 顺序；缓存容量与等待周期均取题目固定配置。\n\n"
        "图 6-2  两场景在同一批 100 个官方计算图上的平均加速比。"
        "单核值按题意置 1，2–5 核各有 100 个官方评估结果；折线表示算术平均。\n\n"
        "图 6-3  100 图平均额外 DDR 搬运量。斜线段为官方字段 "
        "spill_added_copy_bytes；实色段为官方 added_copy_bytes 扣除该字段，"
        "仅称“其余新增搬运”，不全部解释为跨核传输。\n\n"
        "图 6-4  逐图加速比箱线图。每组 100 图，箱体为 25%–75% 分位，"
        "中线为中位数，须为 1.5 倍 IQR，圆点为超出须的观测；不是置信区间。\n\n"
        "数据与复现：图6-2至6-4_逐例源数据.csv、图6-2至6-4_统计摘要.json；"
        "运行 python paper_figures_v2.py。机制图的数据来源为题面与固定 config.txt。\n",
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
