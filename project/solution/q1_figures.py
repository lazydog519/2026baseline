"""Two result figures, with tabular checkpoints instead of decorative charts.

Uses the figure-presets export pattern (PNG + vector PDF); all geometry comes
from the audited metrics or the original evaluator's Task timestamps.
"""
import argparse
import csv
import gzip
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

INK, ACCENT, GRAY = '#252525', '#8F3946', '#929292'


def read_gz(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)


def save(fig,stem):
    fig.savefig(stem.with_suffix('.png'),dpi=260,bbox_inches='tight')
    fig.savefig(stem.with_suffix('.pdf'),bbox_inches='tight')
    plt.close(fig)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--project',type=Path,required=True)
    a=ap.parse_args();p=a.project.resolve();out=p/'q1_cold/final'
    summary=json.loads((out/'aggregate.json').read_text())
    assert summary['complete_cases']==100 and summary['rechecked_jobs']==400 and summary['missing_jobs']==0
    rows=list(csv.DictReader((out/'per_case_metrics.csv').open(encoding='utf-8')))
    checkpoints=[]
    for r in rows:
        events=[json.loads(s) for s in (p/'q1_cold/full'/r['case']/f"n{r['cores']}"/'search.jsonl').read_text().splitlines()]
        ok=[e for e in events if e['status']=='ok']
        assert ok
        for j in range(1,7):
            reached=[e for e in ok if e['evaluation']<=j]
            if not reached:continue
            last=reached[-1]
            checkpoints.append(dict(case=r['case'],cores=r['cores'],evaluation_budget=j,
                completed_evaluations=last['evaluation'],best_cycles=last['best_cycles'],
                speedup=float(r['singlecore_cycles'])/last['best_cycles'],
                elapsed_seconds_at_last_evaluation=last['elapsed_seconds'],
                stopped_before_budget=int(r['evaluations'])<j))
    with (out/'budget_checkpoints.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(checkpoints[0]));w.writeheader();w.writerows(checkpoints)
    with (out/'mean_by_evaluation_budget.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['cores','evaluation_budget','cases_with_feasible_result','mean_speedup','jobs_reaching_budget'])
        for n in range(2,6):
            for j in range(1,7):
                group=[x for x in checkpoints if int(x['cores'])==n and x['evaluation_budget']==j]
                w.writerow([n,j,len(group),statistics.mean(x['speedup'] for x in group),sum(x['completed_evaluations']==j for x in group)])
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
        'font.size':10,'axes.labelsize':10,'axes.titlesize':10,'axes.spines.top':False,'axes.spines.right':False,
        'axes.unicode_minus':False,'pdf.fonttype':42})
    xs=list(range(1,6));ys=[summary['arithmetic_mean_speedup'][str(n)] for n in xs]
    bs=[summary['baseline_mean_speedup'][str(n)] for n in xs]
    fig,ax=plt.subplots(figsize=(6.4,4.25),layout='constrained')
    ax.plot(xs,bs,'s--',c=GRAY,lw=1.25,markersize=4,label='分量基线')
    ax.plot(xs,ys,'o-',c=ACCENT,lw=1.8,markersize=5,label='独立求解 v5')
    for x,y in zip(xs[1:],ys[1:]):ax.annotate(f'{y:.3f}',(x,y),xytext=(0,8),textcoords='offset points',ha='center',color=ACCENT,fontsize=9)
    ax.set(xlabel='可用核心数',ylabel='逐例加速比的算术平均',xticks=xs,ylim=(.85,max(ys+bs)+.42))
    ax.grid(axis='y',lw=.5,alpha=.22);ax.legend(frameon=False,loc='upper left')
    save(fig,out/'01_mean_speedup')

    # Declared development example, never presented as a representative average.
    case='case_051';basepath=next(f/case/'q1_n5/result.json.gz' for f in sorted(p.glob('baseline_results*')) if (f/case/'q1_n5/result.json.gz').is_file())
    before=read_gz(basepath);after=read_gz(p/f'q1_cold/full/{case}/n5/official_result.json.gz')
    row=next(r for r in rows if r['case']==case and r['cores']=='5')
    assert before['makespan']==int(row['baseline_cycles']) and after['makespan']==int(row['makespan_cycles'])
    fig,axs=plt.subplots(2,1,figsize=(8.2,5.7),sharex=True,layout='constrained')
    xmax=max(before['makespan'],after['makespan'])/1000
    for ax,result,color,label in zip(axs,[before,after],[GRAY,ACCENT],['a  分量基线','b  独立求解 v5']):
        count=0
        for core in result['per_core_timeline']:
            tasks=core['tasks'];count+=len(tasks)
            spans=[(t['start']/1000,(t['end']-t['start'])/1000) for t in tasks]
            ax.broken_barh(spans,(core['core_id']-.29,.58),facecolors=color,edgecolors='white',linewidth=.35)
        end=result['makespan']/1000
        ax.axvline(end,c=INK,lw=.7,ls=':')
        ax.set(yticks=range(5),yticklabels=[f'核 {k}' for k in range(5)],ylim=(4.65,-.7),xlim=(0,xmax*1.025))
        ax.set_title(f"{label}    T = {result['makespan']:,} cycles · {count} 个 Task",loc='left',pad=10)
        ax.tick_params(axis='y',length=0);ax.grid(axis='x',alpha=.15,lw=.5)
        m=result['data_movement_bytes']
        ax.text(.995,.025,f"DDR 总搬运 {m['scheduled_copy_bytes']/2**20:.2f} MiB · 换出/换入 {m['spill_added_copy_bytes']/2**20:.2f} MiB",
                transform=ax.transAxes,ha='right',fontsize=8,color=INK)
    axs[1].set_xlabel('官方仿真时间（千 cycles）')
    save(fig,out/'02_case051_task_timeline')
    (out/'图注与数据说明.md').write_text(
        '图 1：100 个用例逐例加速比的算术平均，1 核定义为 1。两条线都使用同一份官方单核参考；'
        '独立求解为冻结 v5，每个 case/core 一个新进程。来自 per_case_metrics.csv；没有对困难用例筛除。\n\n'
        '图 2：开发例 case051、5 核。每条矩形对应原评估器 per_core_timeline.tasks 中一个 Task 的真实起止区间，'
        '包括该 Task 内部等待，不能将填充面积解释为计算利用率。上下共用时间轴；空隙保留，细白边用于区分相邻 Task。'
        '总搬运已包含换入换出，二者不是相互独立的可相加指标；1 MiB = 2^20 bytes。此例用于解释机制，不代表总体平均。\n\n'
        '观察断点：budget_checkpoints.csv 保存每例评估预算 1～6 时的最好已验证周期及当时累计耗时。'
        '提前停止后只延用已有最优值，stopped_before_budget=true；没有虚构新的调用或重新生成方案。'
        'mean_by_evaluation_budget.csv 同时报出有可行结果的例数与真正达到该次数的例数。四进程并发下的墙钟耗时受系统负载影响。\n',encoding='utf-8')
    table=['| 核数 | 分量基线均值 | 独立求解均值 | 改善 / 退化例数 | 耗时中位数（秒） |',
           '|---:|---:|---:|---:|---:|','| 1 | 1.000000 | 1.000000 | 单核定义 | — |']
    for n in range(2,6):
        k=str(n);table.append(f"| {n} | {summary['baseline_mean_speedup'][k]:.6f} | {summary['arithmetic_mean_speedup'][k]:.6f} | {summary['improved_cases'][k]} / {summary['regressed_cases'][k]} | {summary['median_wall_seconds'][k]:.2f} |")
    gain=100*(ys[-1]/bs[-1]-1)
    confirmation=json.loads((p/'q1_cold/confirmation_v5/summary.json').read_text())
    text='\n'.join(table)+f"\n\n全量 100×4 组独立运行，400 份最终方案重新调用原评估器核验一致，114 份原附件哈希未变。五核均值比同核分量基线提高 {gain:.2f}%。"
    if ys[-1]<4.2:text+='尚未达到先前的 4.2 目标，不能通过删例、修改分母或混入旧方案达到目标。'
    text+=f"\n\n全量搜索调用原评估器 {summary['total_official_search_evaluations']} 次，下界剪枝 {summary['total_pruned_candidates']} 次，有条件 3% 证书停止 {summary['certificate_stops']} 组；记录不可行候选 {summary['infeasible_candidates']} 个。最长单进程耗时 {summary['max_wall_seconds']:.2f} 秒，实验并发数为 4。"
    text+=f"\n\n确认样本为预先固定的 10 例：五核均值 {confirmation['means']['5']:.6f}，同批基线 {confirmation['baseline_means']['5']:.6f}；该样本与全量指标分开报告。"
    text+=f"\n\n开发例 case051 五核：{before['makespan']:,} → {after['makespan']:,} cycles。该例总 DDR 搬运从 {before['data_movement_bytes']['scheduled_copy_bytes']/2**20:.2f} 增至 {after['data_movement_bytes']['scheduled_copy_bytes']/2**20:.2f} MiB，却因释放计算并行性而缩短完成时间，说明最小搬运量与最短 Makespan 并不等价。图中时间线仅解释该例；没有据此声称所有图受益于相同机制，也没有把顺序候选比较视为严格模块消融。"
    text+='\n\n个别例超过核数的加速比须结合缓存与搬运减少解释，不能仅按纯计算并行上限判断；本文按原模拟器原样报告。未触发下界证书的用例仍可能有较大改进空间。\n\n![平均加速比](q1_cold/final/01_mean_speedup.png)\n\n![case051 Task 时间线](q1_cold/final/02_case051_task_timeline.png)\n'
    report=p/'技术思路稿-问题一独立求解.md';source=report.read_text(encoding='utf-8')
    start='<!-- Q1_RESULTS_START -->';end='<!-- Q1_RESULTS_END -->'
    source=source[:source.index(start)+len(start)]+'\n'+text+source[source.index(end):]
    report.write_text(source,encoding='utf-8')
    print(json.dumps(dict(figures=2,full_five_core_mean=ys[-1],case051_cycles=after['makespan'])))


if __name__=='__main__':main()
