import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).parent
FIG_DIR = ROOT
FIG_DIR.mkdir(exist_ok=True)
DATA = json.loads((ROOT / "q1_plot_data.json").read_text(encoding="utf-8"))
CORES = np.array([1, 2, 3, 4, 5])
NAVY = "#245A78"
ORANGE = "#C56A2D"
GREY = "#818A91"
TEAL = "#2B7A78"

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "font.size": 9,
    "axes.labelsize": 10,
    "axes.titlesize": 10,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.8,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "savefig.facecolor": "white",
})


def save(fig, name):
    fig.tight_layout()
    for ext, kwargs in (("png", {"dpi": 300}), ("pdf", {}), ("svg", {})):
        fig.savefig(FIG_DIR / f"{name}.{ext}", bbox_inches="tight", **kwargs)
    plt.close(fig)


# Figure 1: mean per-case speedup, baseline versus selected full rerun.
fig, ax = plt.subplots(figsize=(7.2, 4.4))
current = [DATA["summary"][str(n)]["speedup_mean"] for n in CORES]
baseline = [DATA["summary"][str(n)]["baseline_speedup_mean"] for n in CORES]
ax.plot(CORES, baseline, marker="o", lw=1.8, ms=5, color=GREY, label="Component LPT baseline")
ax.plot(CORES, current, marker="o", lw=2.4, ms=5.5, color=NAVY, label="Selected rerun")
ax.set(xlim=(0.85, 5.15), xticks=CORES, xlabel="Core count", ylabel="Mean speedup (×)")
ax.set_ylim(0.75, max(current) * 1.12)
ax.grid(axis="y", color="#D9DEE2", lw=0.7)
ax.set_axisbelow(True)
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2, frameon=False)
save(fig, "q1_mean_speedup")


# Figure 2: fixed benchmark population, sorted paired reduction at five cores.
reductions = np.array([x["reduction_percent"] for x in DATA["casewise_5core"]], dtype=float)
reductions.sort()
fig, ax = plt.subplots(figsize=(7.2, 4.4))
ax.scatter(np.arange(1, len(reductions) + 1), reductions, s=22, color=TEAL,
           alpha=0.78, edgecolors="white", linewidths=0.35, zorder=3)
ax.axhline(0, color=GREY, lw=1, ls="--", zorder=1)
ax.set(xlim=(0, 101), ylim=(-3, max(80, reductions.max() * 1.12)),
       xlabel="Cases, ordered by reduction", ylabel="Makespan reduction vs baseline (%)")
ax.grid(axis="y", color="#D9DEE2", lw=0.7)
ax.set_axisbelow(True)
improved = int(np.count_nonzero(reductions > 1e-12))
ax.text(0.02, 0.90, f"n = {len(reductions)}; improved {improved}; regressed 0",
        transform=ax.transAxes, ha="left", va="top", fontsize=8, color="#333333")
save(fig, "q1_five_core_case_reductions")


# Figure 3: official bytes-per-case summaries; series are distinct evaluator metrics.
fig, ax = plt.subplots(figsize=(7.2, 4.4))
for key, label, color, width in (
    ("scheduled_copy_mean", "Scheduled COPY", GREY, 1.8),
    ("added_copy_mean", "Added COPY", ORANGE, 2.4),
    ("spill_mean", "Spill", TEAL, 1.8),
):
    y = [DATA["summary"][str(n)][key] / 1e6 for n in CORES[1:]]
    ax.plot(CORES[1:], y, marker="o", lw=width, ms=5, color=color, label=label)
ax.set(xlim=(1.85, 5.15), xticks=[2, 3, 4, 5], xlabel="Core count",
       ylabel="Mean bytes per case (millions)")
ax.set_ylim(bottom=0)
ax.grid(axis="y", color="#D9DEE2", lw=0.7)
ax.set_axisbelow(True)
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3, frameon=False)
save(fig, "q1_data_movement")

print(json.dumps({
    "figures": sorted(p.name for p in FIG_DIR.iterdir()),
    "n_cases_5core": len(reductions),
    "improved_5core": improved,
    "reduction_median": float(np.median(reductions)),
    "reduction_min": float(reductions.min()),
    "reduction_max": float(reductions.max()),
}, ensure_ascii=False))
