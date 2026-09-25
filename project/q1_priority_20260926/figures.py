"""Two data-driven, print-sized Scene-A paper figures (Python/matplotlib)."""
import csv
import math
import statistics
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
BLUE, ORANGE, GRAY = '#176A8A', '#B96838', '#66737A'


def read_csv(name):
    with (ROOT/name).open(encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def save(fig, stem):
    out = ROOT/'figures'
    out.mkdir(exist_ok=True)
    for ext, kwargs in (('png', {'dpi': 350}), ('pdf', {}), ('svg', {})):
        fig.savefig(out/f'{stem}.{ext}', bbox_inches='tight', facecolor='white', **kwargs)
    plt.close(fig)


def main():
    rows = read_csv('full_metrics.csv')
    if len(rows) != 400 or any(r['status'] != 'ok' for r in rows):
        raise ValueError('official 100 x 4 metrics incomplete')
    comparator = {r['case']:r for r in read_csv('component_comparator.csv')}
    if len(comparator) != 100:
        raise ValueError('component comparator incomplete')
    mpl.rcParams.update({'font.family':'sans-serif', 'font.sans-serif':['Microsoft YaHei','Arial'],
                         'font.size':8, 'axes.labelsize':9, 'axes.titlesize':9,
                         'pdf.fonttype':42, 'svg.fonttype':'none',
                         'axes.spines.top':False, 'axes.spines.right':False,
                         'axes.linewidth':0.75, 'xtick.major.width':0.75,
                         'ytick.major.width':0.75, 'savefig.pad_inches':0.06,
                         'axes.unicode_minus':False})
    per_n = {n:[float(r['speedup']) for r in rows if int(r['cores'])==n] for n in (2,3,4,5)}
    if any(len(v)!=100 for v in per_n.values()):
        raise ValueError('one or more core counts missing')
    xs = [1,2,3,4,5]
    means = [1.0]+[statistics.mean(per_n[n]) for n in xs[1:]]
    q1 = [1.0]+[statistics.quantiles(per_n[n], n=4, method='inclusive')[0] for n in xs[1:]]
    q3 = [1.0]+[statistics.quantiles(per_n[n], n=4, method='inclusive')[2] for n in xs[1:]]
    fig, ax = plt.subplots(figsize=(5.6,3.25), layout='constrained')
    ax.fill_between(xs, q1, q3, color=BLUE, alpha=0.13, linewidth=0)
    ax.plot(xs, means, color=BLUE, linewidth=1.9, marker='o', markersize=4.5)
    for x,y in zip(xs,means):
        ax.annotate(f'{y:.2f}', (x,y), xytext=(0,7), textcoords='offset points',
                    ha='center', color=BLUE, fontsize=8)
    ax.set(xlim=(0.75,5.25), xticks=xs, xlabel='AI 核数', ylabel='平均加速比')
    ax.set_ylim(bottom=0.7, top=max(max(q3),max(means))*1.13)
    ax.grid(axis='y', color='#DDE2E5', linewidth=0.65)
    ax.set_axisbelow(True)
    ax.text(0.99,0.02,'阴影：逐图加速比的第 25–75 百分位',transform=ax.transAxes,
            ha='right',va='bottom',fontsize=7,color=GRAY)
    save(fig,'图1_问题一核数与平均加速比')

    paired = []
    for r in rows:
        if int(r['cores'])!=5:
            continue
        base = comparator[r['case']]
        cycles = float(r['makespan_cycles'])
        delta_mib = (float(r['added_copy_bytes'])-float(base['component_added_copy_bytes']))/1048576
        gain_pct = (1-cycles/float(base['component_cycles']))*100
        paired.append(dict(case=r['case'], proposed_cycles=cycles,
                           component_cycles=float(base['component_cycles']),
                           extra_ddr_mib=delta_mib, time_gain_percent=gain_pct))
    if len(paired)!=100:
        raise ValueError('five-core cases missing')
    changed = [r for r in paired if abs(r['extra_ddr_mib'])>1e-9 or abs(r['time_gain_percent'])>1e-9]
    improved = sum(r['time_gain_percent']>1e-6 for r in paired)
    worsened = sum(r['time_gain_percent']< -1e-6 for r in paired)
    with (ROOT/'figure_source.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(paired[0]))
        writer.writeheader();writer.writerows(sorted(paired,key=lambda x:x['case']))
    fig, ax = plt.subplots(figsize=(5.6,3.55),layout='constrained')
    for sign,color,label in ((1,BLUE,'耗时改善'),(-1,ORANGE,'耗时退步'),(0,GRAY,'耗时持平')):
        group = [r for r in changed if (1 if r['time_gain_percent']>1e-6 else -1 if r['time_gain_percent']< -1e-6 else 0)==sign]
        if group:
            ax.scatter([r['extra_ddr_mib'] for r in group], [r['time_gain_percent'] for r in group],
                       s=25,alpha=0.79,color=color,edgecolor='white',linewidth=0.35,label=f'{label}（{len(group)}）')
    ax.axhline(0,color=GRAY,linewidth=0.8)
    ax.axvline(0,color=GRAY,linewidth=0.8)
    ax.set(xlabel='相比分量装箱的额外 DDR 搬运差值（MiB）', ylabel='相比分量装箱的耗时改善（%）')
    ax.grid(color='#E8ECEE',linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc='best',fontsize=7,frameon=False)
    ax.text(0.99,0.02,f'五核，100 图；改善 {improved}，退步 {worsened}，持平 {100-improved-worsened}',
            transform=ax.transAxes,ha='right',va='bottom',fontsize=7,color=GRAY)
    save(fig,'图2_问题一耗时与搬运权衡')
    (ROOT/'图注.md').write_text(
        f'图 1  场景 A 中 100 个正式用例的核数扩展。实线为逐图加速比的算术平均，阴影为第 25–75 百分位；'
        f'单核按题意定义为 1，2–5 核均由冻结方案经原版评估器计算。五核平均为 {means[-1]:.4f}。\n\n'
        f'图 2  场景 A 五核方案相对独立分量装箱的成对差值。横轴是官方额外 DDR 搬运之差，纵轴为'
        f'官方 Makespan 的百分比改善；每点为同一个计算图，未改变的图留在原点且不重复绘制。'
        f'100 图中耗时改善 {improved} 图、退步 {worsened} 图、持平 {100-improved-worsened} 图。'
        f'分量装箱比较结果已逐图核对方案与固定配置，未参与求解器训练或选择。\n',
        encoding='utf-8')
    print('figures ready', 'mean5',means[-1], 'changed',len(changed))


if __name__=='__main__':
    main()
