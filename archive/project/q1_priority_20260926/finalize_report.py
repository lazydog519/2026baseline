"""Insert only complete official results into the Chinese method draft."""
import csv
import json
import statistics
from pathlib import Path


def main():
    root=Path(__file__).resolve().parent
    summary=json.loads((root/'full_summary.json').read_text(encoding='utf-8'))
    if summary['complete_cases']!=100 or summary['jobs']!=400 or summary['failed']:
        raise ValueError('official acceptance incomplete')
    with (root/'full_metrics.csv').open(encoding='utf-8') as stream:
        rows=list(csv.DictReader(stream))
    if len(rows)!=400 or any(r['status']!='ok' for r in rows):
        raise ValueError('not 400 valid official rows')
    table=[]
    tex=['% 问题一正式官方验收：100 图，n=2,3,4,5；n=1 按题意固定为 1。',
         '\\begin{tabular}{rrrrr}',
         '\\toprule',
         '核数 & 平均加速比 & 平均 Makespan (cycle) & 平均额外搬运 (MiB) & 平均溢出搬运 (MiB) \\\\',
         '\\midrule']
    for n in (2,3,4,5):
        subset=[r for r in rows if int(r['cores'])==n]
        if len(subset)!=100:
            raise ValueError(f'core {n} missing')
        speed=statistics.mean(float(r['speedup']) for r in subset)
        cycles=statistics.mean(float(r['makespan_cycles']) for r in subset)
        added=statistics.mean(float(r['added_copy_bytes']) for r in subset)/1048576
        spill=statistics.mean(float(r['spill_added_copy_bytes']) for r in subset)/1048576
        table.append(f'| {n} | {speed:.4f} | {cycles:,.0f} | {added:.3f} | {spill:.3f} |')
        tex.append(f'{n} & {speed:.4f} & {cycles:.0f} & {added:.3f} & {spill:.3f} \\\\')
    tex.extend(['\\bottomrule','\\end{tabular}'])
    (root/'正式结果表.tex').write_text('\n'.join(tex)+'\n',encoding='utf-8')
    comp={r['case']:r for r in csv.DictReader((root/'component_comparator.csv').open(encoding='utf-8'))}
    five=[r for r in rows if int(r['cores'])==5]
    faster=sum(float(r['makespan_cycles'])<float(comp[r['case']]['component_cycles']) for r in five)
    slower=sum(float(r['makespan_cycles'])>float(comp[r['case']]['component_cycles']) for r in five)
    mean_delta=statistics.mean((1-float(r['makespan_cycles'])/float(comp[r['case']]['component_cycles']))*100 for r in five)
    content=('正式全量验收覆盖 100 个题目用例、每例 2～5 核各一次，共 400 份冻结方案；'
             '结构与官方评估均无失败。单核加速比按题意取 1，不单独搜索。'
             '下表的加速比先逐图按整图单核时间除以多核 Makespan，再取 100 图算术平均；'
             '搬运以 1 MiB = 1048576 byte 换算。\n\n'
             '| 核数 | 平均加速比 | 平均 Makespan（cycle） | 平均额外搬运（MiB） | 平均溢出搬运（MiB） |\n'
             '|---:|---:|---:|---:|---:|\n'+'\n'.join(table)+'\n\n'
             f'五核与同图分量装箱的官方结果成对比较：{faster} 图耗时更低、{slower} 图更高、'
             f'{100-faster-slower} 图持平；逐图耗时改善百分比的算术平均为 {mean_delta:.2f}%。'
             '这是当前固定策略在给定 100 图上的结果，不能外推成未见图上的保证。'
             '图 1 和图 2 分别展示核数扩展与耗时/搬运代价关系，源数据见 `full_metrics.csv`、'
             '`component_comparator.csv` 和 `figure_source.csv`。')
    path=root/'问题一方法与实验稿.md';text=path.read_text(encoding='utf-8')
    left,right='<!-- RESULTS_BEGIN -->','<!-- RESULTS_END -->'
    if text.count(left)!=1 or text.count(right)!=1:
        raise ValueError('result markers absent or duplicate')
    text=text[:text.index(left)+len(left)]+'\n'+content+'\n'+text[text.index(right):]
    path.write_text(text,encoding='utf-8')
    print(f'official results inserted; mean five-core speedup = {summary["mean_speedup_by_cores"]["5"]:.6f}')


if __name__=='__main__':main()
