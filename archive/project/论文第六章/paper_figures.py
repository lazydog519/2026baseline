"""Two print-ready figures from frozen official Scene-A and Scene-B results."""
import csv
import statistics
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
BLUE, ORANGE, GRAY = '#205F7B', '#BF7045', '#67757B'


def read(path):
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 400 or any(r['status'] != 'ok' for r in rows):
        raise ValueError(f'official 100 × 4 results incomplete: {path}')
    return {(r['case'], int(r['cores'])): r for r in rows}


def save(fig, stem):
    out = ROOT/'figures'
    out.mkdir(exist_ok=True)
    for ext, kwargs in (('png', {'dpi': 400}), ('pdf', {}), ('svg', {})):
        fig.savefig(out/f'{stem}.{ext}', bbox_inches='tight', facecolor='white', **kwargs)
    plt.close(fig)


def main():
    a = read(PROJECT/'q1_priority_20260926/full_metrics.csv')
    b = read(PROJECT/'q2_priority_20260926/final_v2/full_metrics.csv')
    if set(a) != set(b) or len(a) != 400:
        raise ValueError('paired case/core results differ')
    mpl.rcParams.update({
        'font.family': 'sans-serif', 'font.sans-serif': ['Microsoft YaHei', 'Arial'],
        'font.size': 8, 'axes.labelsize': 9, 'axes.titlesize': 9,
        'pdf.fonttype': 42, 'svg.fonttype': 'none', 'axes.spines.top': False,
        'axes.spines.right': False, 'axes.linewidth': 0.8,
        'xtick.major.width': 0.8, 'ytick.major.width': 0.8,
        'axes.unicode_minus': False, 'legend.frameon': False,
    })
    out = ROOT/'figures'
    out.mkdir(exist_ok=True)
    with (out/'paired_source.csv').open('w', encoding='utf-8', newline='') as stream:
        names = ['case', 'cores', 'q1_speedup', 'q2_speedup', 'q1_cycles', 'q2_cycles',
                 'q1_extra_bytes', 'q2_extra_bytes']
        writer = csv.DictWriter(stream, names)
        writer.writeheader()
        for case, n in sorted(a):
            writer.writerow(dict(case=case, cores=n, q1_speedup=a[case,n]['speedup'],
                                 q2_speedup=b[case,n]['speedup'],
                                 q1_cycles=a[case,n]['makespan_cycles'],
                                 q2_cycles=b[case,n]['makespan_cycles'],
                                 q1_extra_bytes=a[case,n]['added_copy_bytes'],
                                 q2_extra_bytes=b[case,n]['added_copy_bytes']))
    ns = [1, 2, 3, 4, 5]
    means_a = [1.0]+[statistics.mean(float(a[c,n]['speedup'])
                  for c in (f'case_{i:03d}' for i in range(1,101))) for n in ns[1:]]
    means_b = [1.0]+[statistics.mean(float(b[c,n]['speedup'])
                  for c in (f'case_{i:03d}' for i in range(1,101))) for n in ns[1:]]
    fig, ax = plt.subplots(figsize=(6.25, 3.45), layout='constrained')
    ax.plot(ns, means_a, '-o', color=BLUE, lw=1.8, ms=5, label='场景 A：每子图一 Task')
    ax.plot(ns, means_b, '-s', color=ORANGE, lw=1.8, ms=4.8,
            label='场景 B：同核子图合并')
    for xs, ys, color, offset in ((ns[1:], means_a[1:], BLUE, (-7, -13)),
                                  (ns[1:], means_b[1:], ORANGE, (7, 7))):
        for x, y in zip(xs, ys):
            ax.annotate(f'{y:.2f}', (x, y), xytext=offset, textcoords='offset points',
                        ha='center', fontsize=7.5, color=color)
    ax.set(xlim=(0.75, 5.25), xticks=ns, xlabel='AI 核数', ylabel='平均加速比')
    ax.set_ylim(0.7, max(means_a+means_b)*1.12)
    ax.grid(axis='y', color='#DEE4E6', lw=0.65)
    ax.set_axisbelow(True)
    ax.legend(loc='upper left', fontsize=7.5)
    ax.text(0.99, 0.03, '100 个计算图；单核按题意取 1',
            transform=ax.transAxes, ha='right', va='bottom', color=GRAY, fontsize=7)
    save(fig, '图6-1_两场景平均加速比')

    pairs = []
    for i in range(1, 101):
        case, n = f'case_{i:03d}', 5
        q1, q2 = a[case,n], b[case,n]
        gain = 100*(float(q1['makespan_cycles'])-float(q2['makespan_cycles']))/float(q1['makespan_cycles'])
        ddr = (float(q2['added_copy_bytes'])-float(q1['added_copy_bytes']))/1048576
        pairs.append((case, ddr, gain))
    fig, ax = plt.subplots(figsize=(6.25, 3.65), layout='constrained')
    groups = (([(x,y) for _,x,y in pairs if y>0], BLUE, 'B 更快'),
              ([(x,y) for _,x,y in pairs if y<0], ORANGE, 'B 更慢'),
              ([(x,y) for _,x,y in pairs if y==0], GRAY, '耗时相同'))
    for group, color, label in groups:
        if group:
            ax.scatter([x for x,_ in group], [y for _,y in group],
                       s=46 if label == '耗时相同' else 27,
                       alpha=0.85, color=color, edgecolors='white', linewidths=0.4,
                       label=f'{label}（{len(group)} 图）', zorder=3)
    ax.axhline(0, color=GRAY, lw=0.85)
    ax.axvline(0, color=GRAY, lw=0.85)
    # A signed logarithmic scale keeps the large DDR-saving cases visible
    # without flattening the observations near zero.
    ax.set_xscale('symlog', linthresh=0.1)
    ax.set_xticks([-100, -10, -1, 0, 1, 10])
    ax.set_xlim(-350, 20)
    ax.annotate('50 图重合', (0, 0), xytext=(7, 7),
                textcoords='offset points', fontsize=7, color=GRAY)
    ax.set(xlabel='场景 B 相对 A 的额外 DDR 搬运差值（MiB）',
           ylabel='场景 B 相对 A 的 Makespan 改善（%）')
    ax.grid(color='#E9EDEF', lw=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc='best', fontsize=7.5)
    save(fig, '图6-2_五核耗时与搬运成对比较')
    (out/'图注.md').write_text(
        f'图 6-1  两种场景在同一批 100 个计算图上的平均加速比。'
        f'曲线由冻结方案经原版评估器得到，单核按题意取 1；'
        f'五核场景 A 为 {means_a[-1]:.4f}，场景 B 为 {means_b[-1]:.4f}。\n\n'
        f'图 6-2  五核时同一计算图在两种场景下的成对变化。'
        f'横轴为官方额外 DDR 搬运量之差，纵轴为官方 Makespan 的相对改善；'
        f'正纵值表示场景 B 更快；横轴为对称对数刻度（0 附近线性），'
        f'50 个零差值图在原点重合。未进行显著性检验。\n\n'
        f'数据源：paired_source.csv；复现：python paper_figures.py。\n',
        encoding='utf-8')
    print('figures ready', means_a[-1], means_b[-1])


if __name__ == '__main__':
    main()
