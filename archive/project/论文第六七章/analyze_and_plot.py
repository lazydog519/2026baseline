"""Rebuild manuscript statistics and monochrome figures from frozen inputs/results."""
import csv
import hashlib
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
import numpy as np

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
sys.path.insert(0, str(PROJECT / 'q1_priority_20260926'))
from q1_optimized import compute_dag, topological_depth


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def read_metrics(folder):
    with (folder / 'full_metrics.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 400 and all(r['status'] == 'ok' for r in rows)
    assert len({(r['case'], int(r['cores'])) for r in rows}) == 400
    return {(r['case'], int(r['cores'])): r for r in rows}


def save(fig, stem):
    for ext in ('png', 'pdf', 'svg'):
        path = ROOT / 'figures' / f'{stem}.{ext}'
        fig.savefig(path, dpi=350, bbox_inches='tight', pad_inches=0.04)
        if ext == 'svg':
            path.write_text('\n'.join(s.rstrip() for s in path.read_text(encoding='utf-8').splitlines())+'\n', encoding='utf-8')
    plt.close(fig)


def main():
    (ROOT / 'figures').mkdir(parents=True, exist_ok=True)
    (ROOT / 'data').mkdir(exist_ok=True)
    frozen = {}
    for folder in (PROJECT / 'q1_priority_20260926', PROJECT / 'q2_priority_20260926/final_v2'):
        summary = json.loads((folder / 'full_summary.json').read_text(encoding='utf-8'))
        for name, expected in summary['source_sha256'].items():
            actual = hashlib.sha256((folder / name).read_bytes()).hexdigest()
            assert actual == expected, (folder, name)
            frozen[str((folder / name).relative_to(PROJECT))] = actual
    features = []
    for i in range(1, 101):
        path = PROJECT / 'official/data' / f'case_{i:03d}.json'
        graph = json.loads(path.read_text(encoding='utf-8'))
        ops, pred, succ = compute_dag(graph)
        order, depth = topological_depth(ops, pred, succ)
        unseen, comps = set(ops), []
        while unseen:
            stack = [min(unseen)]; unseen.remove(stack[0]); members = []
            while stack:
                u = stack.pop(); members.append(u)
                for v in (pred[u] | succ[u]) & unseen:
                    unseen.remove(v); stack.append(v)
            comps.append(members)
        work = sum(o['cycles'] for o in ops.values())
        comp_work = [sum(ops[o]['cycles'] for o in c) for c in comps]
        features.append(dict(case=path.stem, compute_ops=len(ops),
            op_edges=sum(map(len, succ.values())), components=len(comps),
            depth=max(depth.values(), default=0),
            branches=sum(len(succ[o])>1 for o in ops), joins=sum(len(pred[o])>1 for o in ops),
            max_layer_width=max(Counter(depth.values()).values(), default=0),
            compute_cycles=work, largest_component_fraction=max(comp_work, default=0)/max(work, 1),
            direct_op_edges=sum(e['source'] in ops and e['target'] in ops for e in graph['edges']),
            input_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    write_csv(ROOT / 'data/100例结构特征.csv', features)
    a = read_metrics(PROJECT / 'q1_priority_20260926')
    b = read_metrics(PROJECT / 'q2_priority_20260926/final_v2')
    merged = []
    for key in sorted(a):
        row = dict(case=key[0], cores=key[1])
        for prefix, src in (('A', a), ('B', b)):
            for col in ('speedup', 'makespan_cycles', 'added_copy_bytes', 'spill_added_copy_bytes'):
                row[f'{prefix}_{col}'] = float(src[key][col])
        merged.append(row)
    write_csv(ROOT / 'data/两场景逐例结果.csv', merged)
    stats = {'input_cases': 100, 'single_component_cases': sum(r['components']==1 for r in features),
             'multi_component_cases': sum(r['components']>1 for r in features),
             'direct_op_edges': sum(r['direct_op_edges'] for r in features), 'A': {}, 'B': {}}
    for col in ('compute_ops', 'components', 'depth', 'branches', 'joins', 'max_layer_width'):
        vals = [r[col] for r in features]
        stats[col] = {'min': min(vals), 'median': st.median(vals), 'max': max(vals)}
    for name, rows in (('A', a), ('B', b)):
        for n in range(2, 6):
            rr = [r for (c, nc), r in rows.items() if nc==n]
            vals = [float(r['speedup']) for r in rr]
            stats[name][str(n)] = dict(mean=st.mean(vals), median=st.median(vals),
                min=min(vals), max=max(vals),
                added_mib=st.mean(float(r['added_copy_bytes']) for r in rr)/1048576,
                spill_mib=st.mean(float(r['spill_added_copy_bytes']) for r in rr)/1048576)
    five = [r for r in merged if r['cores']==5]
    stats['paired5'] = dict(faster=sum(r['B_makespan_cycles']<r['A_makespan_cycles'] for r in five),
        slower=sum(r['B_makespan_cycles']>r['A_makespan_cycles'] for r in five),
        same=sum(r['B_makespan_cycles']==r['A_makespan_cycles'] for r in five),
        mean_time_reduction=st.mean((r['A_makespan_cycles']-r['B_makespan_cycles'])/r['A_makespan_cycles'] for r in five))
    groups = [[float(a[r['case'], 5]['speedup']) for r in features if (r['components']==1)==single]
              for single in (True, False)]
    stats['A_structure5'] = [dict(n=len(g), mean=st.mean(g), median=st.median(g)) for g in groups]
    (ROOT / 'data/统计摘要.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (ROOT / 'data/冻结代码核对.json').write_text(json.dumps(frozen, indent=2)+'\n', encoding='utf-8')
    plt.rcParams.update({'font.family': ['SimSun', 'Times New Roman'], 'font.size': 9,
        'mathtext.fontset': 'stix', 'axes.unicode_minus': False,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.linewidth': 0.75, 'legend.frameon': False, 'pdf.fonttype': 42, 'svg.fonttype': 'none'})
    ns = np.arange(1, 6)
    av = [1]+[stats['A'][str(n)]['mean'] for n in ns[1:]]
    bv = [1]+[stats['B'][str(n)]['mean'] for n in ns[1:]]
    fig, ax = plt.subplots(1, 2, figsize=(6.65, 2.8), layout='constrained')
    ax[0].plot(ns, av, 'o-', color='black', markersize=4, linewidth=1)
    ax[0].set(xlabel='AI 核数', ylabel='平均加速比', xticks=ns, ylim=(0.9, 4.15))
    ax[0].annotate(f'{av[-1]:.3f}', (5, av[-1]), xytext=(-4, 8), textcoords='offset points', ha='right')
    ax[0].set_title('(a) 核数与平均加速比', fontsize=9)
    ax[1].boxplot(groups, tick_labels=[f'单分量\n(n={len(groups[0])})', f'多分量\n(n={len(groups[1])})'],
        widths=0.45, patch_artist=True, boxprops={'facecolor':'white', 'edgecolor':'black'},
        medianprops={'color':'black'}, flierprops={'marker':'.','markersize':3, 'markeredgecolor':'black'})
    ax[1].set(ylabel='五核加速比'); ax[1].set_title('(b) 不同结构的加速比分布', fontsize=9)
    save(fig, '图6-1_问题一求解结果')
    fig, axes = plt.subplots(2, 1, figsize=(6.65, 2.75))
    for ax in axes: ax.set(xlim=(0,10), ylim=(0,1)); ax.axis('off')
    def box(ax,x,y,w,h,label):
        ax.add_patch(Rectangle((x,y),w,h,fill=False,linewidth=0.8))
        ax.text(x+w/2,y+h/2,label,ha='center',va='center',fontsize=9)
    def arrow(ax,x0,x1,y): ax.add_patch(FancyArrowPatch((x0,y),(x1,y),arrowstyle='->',mutation_scale=10,lw=0.8,color='black'))
    ax=axes[0]
    ax.text(0,0.87,'(a) 场景 A：同核子图之间仍经 DDR 中转',fontsize=9)
    box(ax,0.1,0.16,2.3,0.48,'Task 1：子图 $s_1$')
    box(ax,3.6,0.16,2.8,0.48,'DDR 写回 / 读入')
    box(ax,7.6,0.16,2.3,0.48,'Task 2：子图 $s_2$')
    arrow(ax,2.4,3.6,0.40);arrow(ax,6.4,7.6,0.40)
    ax=axes[1]
    ax.text(0,0.92,'(b) 场景 B：同核子图合并，保留 L1/UB 中的可用数据',fontsize=9)
    box(ax,0.1,0.21,6.3,0.50,'同核单一 Task：$s_1$ → L1/UB 复用 → $s_2$')
    box(ax,7.6,0.21,2.3,0.50,'共享 DDR')
    arrow(ax,6.4,7.6,0.46)
    ax.text(5,0.01,'跨核传输和缓存换入/换出仍占用 DDR；并发搬运共享总带宽。',ha='center',fontsize=8)
    fig.subplots_adjust(left=0.015,right=0.985,top=0.97,bottom=0.04,hspace=0.25)
    save(fig, '图7-1_Task边界与数据复用')
    fig, ax=plt.subplots(1,2,figsize=(6.65,2.9),layout='constrained')
    ax[0].plot(ns,av,'o-',color='black',markersize=3.5,lw=1,label='问题一（场景 A）')
    ax[0].plot(ns,bv,'s--',color='0.4',markersize=3.5,lw=1,label='问题二（场景 B）')
    ax[0].set(xlabel='AI 核数',ylabel='平均加速比',xticks=ns); ax[0].legend(fontsize=8)
    ax[0].set_title('(a) 两场景的平均加速比',fontsize=9)
    x=np.arange(2,6); width=0.32
    for name,shift,fill,hatch,label in [('A',-width/2,'white','///','场景 A'),('B',width/2,'0.65','','场景 B')]:
        ax[1].bar(x+shift,[stats[name][str(n)]['added_mib'] for n in x],width,
                  color=fill,edgecolor='black',linewidth=0.65,hatch=hatch,label=label)
    ax[1].set(xlabel='AI 核数',ylabel='平均额外 DDR 搬运（MiB）',xticks=x,ylim=(0,18))
    ax[1].set_title('(b) 两场景的额外搬运量',fontsize=9);ax[1].legend(fontsize=8)
    save(fig, '图7-2_问题二求解结果')
    print(json.dumps(stats,ensure_ascii=False))


if __name__ == '__main__': main()
