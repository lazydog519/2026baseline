"""Produce one progress figure and descriptive matched-budget results."""
import csv
import json
import re
import statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parent


def main():
    cfg=json.loads((ROOT/'experiment.json').read_text())
    verification=json.loads((ROOT/'experiment/verification.json').read_text())
    assert verification['completed_jobs']==27 and verification['equal_official_budgets']
    rows=list(csv.DictReader((ROOT/'experiment/metrics.csv').open(encoding='utf-8')))
    summaries=[]
    for case in cfg['cases']:
        for method in cfg['methods']:
            group=[r for r in rows if r['case']==case and r['method']==method]
            values=[int(r['makespan']) for r in group]
            summaries.append(dict(case=case,method=method,n=len(values),
                mean_makespan=statistics.mean(values),min_makespan=min(values),max_makespan=max(values),
                sd_makespan=statistics.stdev(values),construction_best=int(group[0]['construction_best']),
                mean_construction_ratio=statistics.mean(float(r['construction_ratio']) for r in group),
                mean_same_plan_cache_ratio=statistics.mean(float(r['same_plan_cache_ratio']) for r in group),
                mean_calls=statistics.mean(int(r['official_calls']) for r in group),
                invalid_total=sum(int(r['invalid']) for r in group)))
    comparisons=[]
    for method in cfg['methods'][1:]:
        matched=[]
        for case in cfg['cases']:
            for seed in cfg['seeds']:
                ref=next(r for r in rows if r['case']==case and r['method']=='nsga3_generic' and int(r['seed'])==seed)
                other=next(r for r in rows if r['case']==case and r['method']==method and int(r['seed'])==seed)
                matched.append(int(ref['makespan'])/int(other['makespan']))
        comparisons.append(dict(method=method,paired_mean_speedup_over_generic=statistics.mean(matched),
            wins=sum(x>1 for x in matched),ties=sum(x==1 for x in matched),losses=sum(x<1 for x in matched),
            scope='9 matched case/seed pairs; repeated seeds do not make 9 independent cases'))
    aggregate=dict(scope=cfg['scope'],rows=27,official_search_calls=sum(int(r['official_calls']) for r in rows),
        official_rechecks=27,paired_no_l2_evaluations=27,cases=cfg['cases'],seeds=cfg['seeds'],
        summaries=summaries,comparisons=comparisons)
    (ROOT/'summary.json').write_text(json.dumps(aggregate,indent=2)+'\n')
    with (ROOT/'summary.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    labels=dict(nsga3_generic='NSGA-III / 通用',nsga3_npu='NSGA-III / NPU',unsga3_npu='U-NSGA-III / NPU')
    colors=['#7A8792','#B77139','#246A88']
    plt.rcParams.update({'font.family':'Microsoft YaHei','font.size':9,'axes.spines.top':False,
                         'axes.spines.right':False,'pdf.fonttype':42,'axes.unicode_minus':False})
    fig,axes=plt.subplots(1,3,figsize=(9.1,3.6),sharey=True)
    fig.subplots_adjust(left=.09,right=.98,bottom=.2,top=.8,wspace=.15)
    curves=[]
    for ax,case in zip(axes,cfg['cases']):
        base=next(s['construction_best'] for s in summaries if s['case']==case)
        for method,color in zip(cfg['methods'],colors):
            data=[]
            for seed in cfg['seeds']:
                log=ROOT/'experiment'/case/'n5'/method/f'seed_{seed}'/'evaluations.jsonl'
                records=[json.loads(s) for s in log.read_text().splitlines()]
                assert len(records)==cfg['official_budget']
                ys=[r['best_makespan']/base for r in records]
                data.append(ys)
                curves.extend(dict(case=case,method=method,seed=seed,official_call=i+1,relative_best=y) for i,y in enumerate(ys))
            data=np.asarray(data);x=np.arange(1,cfg['official_budget']+1)
            ax.plot(x,np.median(data,axis=0),lw=1.5,color=color,label=labels[method])
            ax.fill_between(x,data.min(axis=0),data.max(axis=0),color=color,alpha=.12,linewidth=0)
        ax.axhline(1,color='#555555',ls=':',lw=.7)
        ax.set(title=f'case {case[-3:]} · 5 核',xlabel='官方评估调用次数',xlim=(1,cfg['official_budget']))
    axes[0].set_ylabel('迄今最短时间 / 初始构造最短时间')
    axes[0].set_ylim(.6,1.45)
    fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',ncol=3,frameon=False)
    fig.text(.09,.035,'实线：3 个种子的中位数；阴影：最小—最大范围（非置信区间）。每次搜索固定 30 次官方评估。',fontsize=8,color='#555555')
    for ext in ['png','pdf']:fig.savefig(ROOT/f'convergence.{ext}',dpi=300,bbox_inches='tight')
    plt.close(fig)
    with (ROOT/'convergence_data.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(curves[0]));w.writeheader();w.writerows(curves)
    lines=['## 简化测试结果','',
        '所有数值均为官方模拟 cycles，越小越好。每格使用三个固定种子；初始构造最短时间依次为 '
        + '、'.join(f"{case[-3:]}: {next(s['construction_best'] for s in summaries if s['case']==case):,}" for case in cfg['cases'])+'。','',
        '| 算例 | 方法 | 平均 Makespan | 最小—最大 | 相同方案缓存加速比均值 |',
        '|---|---|---:|---:|---:|']
    for s in summaries:
        lines.append(f"| {s['case'][-3:]} | {labels[s['method']]} | {s['mean_makespan']:,.2f} | {s['min_makespan']:,}—{s['max_makespan']:,} | {s['mean_same_plan_cache_ratio']:.6f} |")
    lines+=['','与同种子、同初始种群的通用 NSGA-III 比较，配对比值定义为通用组时间 / 对应工程组时间：','',
            '| 方法 | 9 组配对比值均值 | 胜／平／负 |','|---|---:|---:|']
    for c in comparisons:
        lines.append(f"| {labels[c['method']]} | {c['paired_mean_speedup_over_generic']:.6f} | {c['wins']}／{c['ties']}／{c['losses']} |")
    lines+=['','上述 9 组来自 3 个算例的重复种子，不能当成 9 个独立算例推断全量；配置比值与算法比值不同，不互相代替。',
        '',f"共 {aggregate['official_search_calls']} 次搜索评估，27 次完整问题三复核、27 次同方案问题二评估；全部最终结果逐字段复核通过。初始种群哈希、原评估预算一致，114 份官方文件和冻结源文件未改变。",
        '', '![同预算搜索过程](convergence.png)',
        '', '**图：同预算三组搜索的收敛过程。** 展示各次调用后最佳时间，阴影仅表示三个种子的最小—最大范围。虚线为本次从输入重建的三个初始构造中最好者，不是从磁盘读取历史答案。数据见 convergence_data.csv。',
        '', '**机制实例。** 044、种子 17 的 U-NSGA-III 工程组，从本次重建的最优初始构造 84,117 降为 59,036 cycles。官方额外 COPY 从 3,721,600 降为 2,763,680 bytes，DDR 未命中读取从 4,672,544 降为 2,600,768 bytes；与此同时跨核传输连接从 0 增至 79。这说明不能只盯住零跨核割集：重复图输入、访问时序与中间通信需要一并考虑。上述量是同一运行前后的共同变化，不是各算子独立因果贡献。源数据见 mechanism_case044.json。',
        '', '**结论边界。** 改善主要集中在 044；074 中 U-NSGA-III 工程组均值反而略差于通用组。两种工程组相对通用组均为 4 胜、1 平、4 负，当前不足以认定工程变异或 U 竞争机制稳定优越。它们值得保留为候选，并不支持无条件替换。',
        '', '与旧的至多五次评估方法相比，本轮也增加了预算，因此不能将全部改善归功于 NSGA-III。上表三组均为三十次评估，才是本轮对工程算子和竞争机制的预算受控比较。未进行 100 例全量搜索。','']
    p=ROOT/'README.md';text=p.read_text(encoding='utf-8')
    text=re.sub(r'<!-- RESULTS_START -->.*?<!-- RESULTS_END -->',
                lambda _: '<!-- RESULTS_START -->\n'+'\n'.join(lines)+'\n<!-- RESULTS_END -->',text,flags=re.S)
    p.write_text(text,encoding='utf-8')
    print(json.dumps(aggregate))


if __name__=='__main__':main()
