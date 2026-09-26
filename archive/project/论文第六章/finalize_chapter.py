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
    spill_a=statistics.mean(float(a[f'case_{i:03d}',5]['spill_added_copy_bytes'])
                            for i in range(1,101))/1048576
    spill_b=statistics.mean(float(b[f'case_{i:03d}',5]['spill_added_copy_bytes'])
                            for i in range(1,101))/1048576
    q2_text='\n'.join(lines)+('\n五核时场景 B 的平均加速比为 '
        f'{mean_b[5]:.4f}，{relation}场景 A 的 {mean_a[5]:.4f}。'
        f'逐图配对比较中，B 在 {faster} 图耗时缩短、{slower} 图增加、'
        f'{tied} 图相同；以 A 的逐图耗时为分母，B 的平均耗时缩减率为 '
        f'{100*statistics.mean(relative):+.2f}\\%，'
        f'平均额外搬运差为 {statistics.mean(delta_ddr):+.3f} MiB。'
        '这些是同一批图的描述统计，不能据此断言每个图上 B 都更快。'
        '\n\\begin{figure}[htbp]\n\\centering\n'
        '\\includegraphics[width=0.86\\linewidth]{论文第六章/figures/图6-2_两场景平均加速比.pdf}\n'
        '\\caption{场景 A 与 B 在 100 图上的 1--5 核平均加速比。'
        '单核值按题意定义为 1；其余点各为 100 图算术平均。}\n'
        '\\label{fig:chapter6-speedup}\n\\end{figure}\n'
        '图~\\ref{fig:chapter6-speedup} 显示两场景的平均加速比均随核数增加，'
        '场景 B 在 2--5 核的每个核数上均较高。该曲线报告总体均值，'
        '不能代替逐图分布；单核的 1 是定义值而非另一次多核实验。'
        '\n\\begin{figure}[htbp]\n\\centering\n'
        '\\includegraphics[width=0.86\\linewidth]{论文第六章/figures/图6-3_额外DDR搬运分解.pdf}\n'
        '\\caption{2--5 核的平均额外 DDR 搬运量。斜线段是原版评估程序给出的'
        '缓存换入/换出新增字节，其余部分是总额外搬运扣除该字段；'
        '后者不全部等同于跨核搬运。每根柱对应 100 图的算术平均。}\n'
        '\\label{fig:chapter6-copy}\n\\end{figure}\n'
        f'五核时缓存换入/换出所致新增搬运在 A、B 下的平均值分别为 '
        f'{spill_a:.3f} 和 {spill_b:.3f} MiB。图~\\ref{{fig:chapter6-copy}}'
        ' 说明场景 B 的总额外搬运较低，但两场景的溢出成本都不可忽略；'
        '因此不能把同核直通写成“缓存必定无溢出”。'
        '\n\\begin{figure}[htbp]\n\\centering\n'
        '\\includegraphics[width=0.86\\linewidth]{论文第六章/figures/图6-4_逐图加速比分布.pdf}\n'
        '\\caption{两场景在 2--5 核下的逐图加速比分布。每箱含 100 图；'
        '箱体为第 25--75 百分位，中线为中位数，须延至距四分位数'
        '1.5 倍四分位距内的最远观测，圆点为其外观测；'
        '箱体不是均值置信区间。}\n'
        '\\label{fig:chapter6-box}\n\\end{figure}\n'
        '图~\\ref{fig:chapter6-box} 给出均值曲线之外的离散程度。'
        '五核时 A、B 的逐图中位加速比分别为 4.043、4.148；'
        '结合 31 图改善、19 图退步、50 图持平的配对结果，'
        '场景 B 的收益存在结构依赖，不能从场景规则推出逐图单调改进。'
        '模型中的驻留风险只用于求解阶段的候选筛选，'
        '本节所有性能数值均来自方案冻结后的官方验收。')
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
