"""Mechanism-diagnostic figure from the fresh 192-label development probe."""
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
rows = [json.loads(line) for line in
        (HERE / 'neighbor_calibration_labels.jsonl').read_text(encoding='utf-8').splitlines()]
groups = defaultdict(list)
for row in rows:
    groups[(row['case'], row['cores'], row['question'])].append(row)


def main():
    data = []
    for (case, n, q), group in sorted(groups.items()):
        seed = group[0]
        for row in group[1:]:
            data.append({'case': case, 'cores': n, 'question': q, 'move': row['name'],
                         'proxy_change_pct': 100*(row['proxy']['score']/seed['proxy']['score']-1),
                         'official_time_change_pct': 100*(row['official']['makespan']/seed['official']['makespan']-1),
                         'added_spill_bytes': row['official']['data_movement_bytes']['spill_added_copy_bytes'] -
                                              seed['official']['data_movement_bytes']['spill_added_copy_bytes']})
    with (HERE / 'neighbor_diagnostics_source.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=data[0])
        writer.writeheader(); writer.writerows(data)
    plt.rcParams.update({'font.family': 'Microsoft YaHei', 'font.size': 9,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42, 'svg.fonttype': 'none', 'axes.linewidth': .7})
    fig, axes = plt.subplots(1, 3, figsize=(7.1, 3.1), sharex=True, sharey=True, layout='constrained')
    for q, ax in zip((1, 2, 3), axes):
        part = [r for r in data if r['question'] == q]
        no_spill = [r for r in part if r['added_spill_bytes'] <= 0]
        spill = [r for r in part if r['added_spill_bytes'] > 0]
        ax.scatter([r['proxy_change_pct'] for r in no_spill],
                   [r['official_time_change_pct'] for r in no_spill],
                   s=17, color='#246087', alpha=.72, label='未增加换出')
        if spill:
            ax.scatter([r['proxy_change_pct'] for r in spill],
                       [r['official_time_change_pct'] for r in spill],
                       s=29, marker='^', color='#B96632', label='换出增加')
        ax.axhline(0, color='#666B6C', lw=.7)
        ax.axvline(0, color='#666B6C', lw=.7)
        ax.plot([-20, 80], [-20, 80], color='#AEB5B5', lw=.7, ls='--')
        ax.set(title=['(a) 场景 A', '(b) 场景 B', '(c) 场景 B + L2'][q-1],
               xlabel='解析代理的相对变化（%）', xlim=(-20, 80), ylim=(-20, 90))
        ax.set_axisbelow(True)
        ax.grid(color='#E8EAE9', lw=.45)
        if q == 1:
            ax.set_ylabel('原版 Makespan 相对变化（%）')
        if q == 2:
            ax.legend(loc='upper left', frameon=False, fontsize=7)
    fig.text(.5, -.015, '每点为同一输入图、核数、场景下的一次合法邻域移动；虚线为代理完全准确时的位置。'
             '橙三角显示新增换出风险。', ha='center', va='top', fontsize=7.2)
    for ext in ('png', 'pdf', 'svg'):
        fig.savefig(HERE / f'fig_neighbor_diagnostics.{ext}', dpi=400,
                    bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print({'moves': len(data), 'added_spill_moves': sum(r['added_spill_bytes'] > 0 for r in data)})


if __name__ == '__main__':
    main()
