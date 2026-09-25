"""One evidence-led Pareto figure from official development labels (Python only)."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'all_questions_fresh_v3'
CASE, CORES = 'case_009', 5
COLORS = {1: '#246087', 2: '#C56E31', 3: '#27846D'}


def pareto(rows):
    return [row for row in rows if not any(
        other['cycles'] <= row['cycles'] and other['added_bytes'] <= row['added_bytes'] and
        (other['cycles'], other['added_bytes']) != (row['cycles'], row['added_bytes'])
        for other in rows)]


def main():
    source = json.loads((SOURCE / 'training_labels.json').read_text(encoding='utf-8'))
    rows = [dict(question=r['question'], case=r['case'], cores=r['cores'], method=r['name'],
                 cycles=r['makespan'], added_bytes=r['data_movement_bytes']['added_copy_bytes'],
                 hit_rate=(r.get('cache_stats') or {}).get('hit_rate'))
            for r in source if r['case'] == CASE and r['cores'] == CORES and r['status'] == 'ok']
    with (ROOT / 'tradeoff_source.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    plt.rcParams.update({'font.family': 'Microsoft YaHei', 'font.size': 9,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42, 'svg.fonttype': 'none', 'axes.linewidth': .7})
    fig, axes = plt.subplots(1, 3, figsize=(7.1, 3.0), sharex=True, sharey=True, layout='constrained')
    for q, ax in zip((1, 2, 3), axes):
        part = [r for r in rows if r['question'] == q]
        front = sorted({(r['added_bytes'], r['cycles']) for r in pareto(part)})
        ax.scatter([r['added_bytes']/2**20 for r in part], [r['cycles']/1000 for r in part],
                   s=19, c='#A9B0B3', alpha=.8, zorder=2)
        ax.plot([b/2**20 for b,t in front], [t/1000 for b,t in front],
                color=COLORS[q], lw=1.4, zorder=3)
        low_t = min(part, key=lambda r: (r['cycles'], r['added_bytes']))
        low_b = min(part, key=lambda r: (r['added_bytes'], r['cycles']))
        ax.scatter(low_t['added_bytes']/2**20, low_t['cycles']/1000,
                   marker='*', s=95, color=COLORS[q], edgecolor='white', linewidth=.4, zorder=5)
        ax.scatter(low_b['added_bytes']/2**20, low_b['cycles']/1000,
                   marker='s', s=38, facecolor='white', edgecolor=COLORS[q], linewidth=1.4, zorder=4)
        ax.set(title=['(a) 场景 A', '(b) 场景 B', '(c) 场景 B + 只读 L2'][q-1],
               xlabel='新增 DDR 搬运量（MiB）', xlim=(-.04, 1.02), ylim=(42, 160))
        ax.grid(color='#E7E9E8', linewidth=.5); ax.set_axisbelow(True)
        if q == 1: ax.set_ylabel('Makespan（千周期）')
        if q == 3:
            ax.text(.98, .96, f'最快点命中率 {low_t["hit_rate"]:.1%}', transform=ax.transAxes,
                    ha='right', va='top', fontsize=7.5, color=COLORS[q])
    fig.text(.5, -.015, '灰点：全部可行候选；彩线：时间—搬运量非支配边界；★ 时间最短；□ 搬运最少。单个开发图，仅用于说明取舍。',
             ha='center', va='top', fontsize=7.5)
    for ext in ('png', 'pdf', 'svg'):
        fig.savefig(ROOT / f'fig_tradeoff.{ext}', dpi=400, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(json.dumps({'case': CASE, 'cores': CORES, 'candidates': len(rows),
                      'front_sizes': {q: len(pareto([r for r in rows if r['question']==q])) for q in (1,2,3)}},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
