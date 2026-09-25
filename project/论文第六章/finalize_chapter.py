"""Insert only independently audited 100-case results into Chapter 6."""
import csv
import json
import re
import statistics
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ROOT = Path(__file__).resolve().parent
Q1 = PROJECT/'q1_priority_20260926'
Q2 = PROJECT/'q2_priority_20260926/final_v2'


def csv_rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def read(root):
    summary = json.loads((root/'full_summary.json').read_text(encoding='utf-8'))
    if summary['complete_cases'] != 100 or summary['failed'] != 0:
        raise ValueError(f'incomplete official summary: {root}')
    rows = csv_rows(root/'full_metrics.csv')
    data = {(r['case'], int(r['cores'])): r for r in rows if r['status']=='ok'}
    expected = {(f'case_{i:03d}', n) for i in range(1,101) for n in (2,3,4,5)}
    if set(data) != expected or len(rows) != 400:
        raise ValueError(f'incomplete official metrics: {root}')
    return summary, data


def replace(text, label, new):
    pattern = rf'(?s)(% {label}_BEGIN\n).*?(\n% {label}_END)'
    changed, count = re.subn(pattern, lambda m:m.group(1)+new+m.group(2), text)
    if count != 1:
        raise ValueError(f'missing or duplicate marker: {label}')
    return changed


def main():
    sa, a = read(Q1)
    sb, b = read(Q2)
    for key in a:
        ra, rb = a[key], b[key]
        ta = float(ra['speedup'])*float(ra['makespan_cycles'])
        tb = float(rb['speedup'])*float(rb['makespan_cycles'])
        if abs(ta-tb)>1e-5:
            raise ValueError(f'one-core denominator mismatch: {key}')
    appendix = ROOT/'附录_逐用例官方结果.csv'
    fields = ('case','cores','singlecore_cycles','q1_makespan_cycles',
              'q1_added_copy_bytes','q1_speedup','q2_makespan_cycles',
              'q2_added_copy_bytes','q2_speedup')
    with appendix.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for case, n in sorted(a):
            x,y=a[case,n],b[case,n]
            writer.writerow(dict(case=case,cores=n,
                singlecore_cycles=round(float(x['speedup'])*float(x['makespan_cycles']),6),
                q1_makespan_cycles=x['makespan_cycles'],
                q1_added_copy_bytes=x['added_copy_bytes'],q1_speedup=x['speedup'],
                q2_makespan_cycles=y['makespan_cycles'],
                q2_added_copy_bytes=y['added_copy_bytes'],q2_speedup=y['speedup']))
    mean_a = {n:statistics.mean(float(a[c,n]['speedup']) for c in
              (f'case_{i:03d}' for i in range(1,101))) for n in (2,3,4,5)}
    mean_b = {n:statistics.mean(float(b[c,n]['speedup']) for c in
              (f'case_{i:03d}' for i in range(1,101))) for n in (2,3,4,5)}
    if any(abs(mean_a[n]-sa['mean_speedup_by_cores'][str(n)])>1e-9 or
           abs(mean_b[n]-sb['mean_speedup_by_cores'][str(n)])>1e-9 for n in mean_a):
        raise ValueError('aggregate does not match official per-case rows')
    component = {r['case']:r for r in csv_rows(Q1/'component_comparator.csv')}
    if len(component)!=100:
        raise ValueError('component comparison incomplete')
    changes=[]
    for i in range(1,101):
        case=f'case_{i:03d}'
        cmp=float(component[case]['component_cycles'])
        now=float(a[case,5]['makespan_cycles'])
        changes.append((cmp-now)/cmp)
    improved=sum(x>1e-9 for x in changes)
    regressed=sum(x< -1e-9 for x in changes)
    q1_text=(
        '在固定配置与全部 100 个官方计算图上，先独立生成并冻结 2--5 核各 100 份方案，'
        '再调用未修改的场景 A 评估程序，共 400 次验收，均成功。'
        '按题面单核参照计算，2、3、4、5 核的平均加速比分别为 '
        + '、'.join(f'{mean_a[n]:.4f}' for n in (2,3,4,5)) + '。'
        f'五核相对纯分量装箱的成对比较中，{improved} 图耗时缩短、'
        f'{regressed} 图耗时增加、{100-improved-regressed} 图不变；'
        '因此结构切分并非对所有图都有收益。两场景的核数曲线见图~\\ref{fig:chapter6-speedup}；'
        '逐图 Makespan 和额外搬运量见附录表。'
    )
    lines=[r'\begin{table}[htbp]',r'\centering',
           r'\caption{100 个官方计算图在两种场景下的平均结果。额外搬运以 MiB 表示。}',
           r'\label{tab:chapter6-results}',
           r'\begin{tabular}{ccccc}',r'\hline',
           r'核数 & 场景 A 加速比 & 场景 B 加速比 & A 额外搬运 & B 额外搬运 \\',
           r'\hline',r'1 & 1.0000 & 1.0000 & -- & -- \\']
    for n in (2,3,4,5):
        da=statistics.mean(float(a[f'case_{i:03d}',n]['added_copy_bytes']) for i in range(1,101))/1048576
        db=statistics.mean(float(b[f'case_{i:03d}',n]['added_copy_bytes']) for i in range(1,101))/1048576
        lines.append(f'{n} & {mean_a[n]:.4f} & {mean_b[n]:.4f} & {da:.3f} & {db:.3f} \\\\')
    lines.extend([r'\hline',r'\end{tabular}',r'\end{table}'])
    faster=slower=tied=0
    relative=[]
    delta_ddr=[]
    for i in range(1,101):
        key=(f'case_{i:03d}',5)
        ta,tb=float(a[key]['makespan_cycles']),float(b[key]['makespan_cycles'])
        relative.append((ta-tb)/ta)
        delta_ddr.append((float(b[key]['added_copy_bytes'])-float(a[key]['added_copy_bytes']))/1048576)
        faster+=tb<ta
        slower+=tb>ta
        tied+=tb==ta
    relation='高于' if mean_b[5]>mean_a[5] else '低于或等于'
    q2_text='\n'.join(lines)+('\n五核时场景 B 的平均加速比为 '
        f'{mean_b[5]:.4f}，{relation}场景 A 的 {mean_a[5]:.4f}。'
        f'逐图配对比较中，B 在 {faster} 图耗时缩短、{slower} 图增加、'
        f'{tied} 图相同；五核平均耗时变化为 {100*statistics.mean(relative):+.2f}\\%，'
        f'平均额外搬运差为 {statistics.mean(delta_ddr):+.3f} MiB。'
        '这些是同一批图的描述统计，不能据此断言每个图上 B 都更快。'
        '\n\\begin{figure}[htbp]\n\\centering\n'
        '\\includegraphics[width=0.83\\linewidth]{论文第六章/figures/图6-1_两场景平均加速比.pdf}\n'
        '\\caption{100 图在场景 A、B 下的 1--5 核平均加速比；单核值按题意为 1。}\n'
        '\\label{fig:chapter6-speedup}\n\\end{figure}\n'
        '\\begin{figure}[htbp]\n\\centering\n'
        '\\includegraphics[width=0.83\\linewidth]{论文第六章/figures/图6-2_五核耗时与搬运成对比较.pdf}\n'
        '\\caption{五核时场景 B 相对 A 的逐图耗时改善与额外 DDR 搬运变化。}\n'
        '\\label{fig:chapter6-paired}\n\\end{figure}\n'
        '图~\\ref{fig:chapter6-paired} 同时呈现收益与代价：'
        '横轴是额外搬运差、纵轴是 Makespan 的相对改善。'
        '模型中的驻留风险只是候选筛选量；论文结果均取自官方程序。')
    chapter=ROOT/'第六章_问题一与问题二建模求解.tex'
    text=chapter.read_text(encoding='utf-8')
    text=replace(text,'Q1_RESULTS',q1_text)
    text=replace(text,'Q2_RESULTS',q2_text)
    chapter.write_text(text,encoding='utf-8')
    report=dict(q1_mean_speedup_by_cores=mean_a,q2_mean_speedup_by_cores=mean_b,
                q2_five_core_higher=mean_b[5]>mean_a[5],
                q1_component_improved=improved,q1_component_regressed=regressed,
                q2_five_core_faster=faster,q2_five_core_slower=slower,
                q2_five_core_equal=tied,
                q2_five_core_mean_relative_time_gain=statistics.mean(relative),
                q2_five_core_mean_extra_ddr_delta_mib=statistics.mean(delta_ddr),
                official_jobs_per_scene=400)
    (ROOT/'第六章_核对摘要.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',
                                               encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
