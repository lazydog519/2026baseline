"""Check frozen evidence, aggregate paired audits, and make two paper figures.

Plot layout adapts mathodology F01/F05 to paired core-count curves and FIFO
event evidence. No synthetic data, smoothing or inferred confidence intervals.
"""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import statistics as st
from collections import Counter

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
RUNS = [ROOT/'full1to4_v2', ROOT/'full5_v2']
FINAL = ROOT/'final'
FIGS = PROJECT/'论文第六章/figures'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def save(p, x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def aggregate():
    rows, reports, locations = [], {}, {}
    reference = read(RUNS[0]/'generation_manifest.json')
    for name,h in reference['source_sha256'].items():
        assert sha(ROOT/name)==h, ('frozen source',name)
    for name,h in reference['official_sha256'].items():
        assert sha(PROJECT/'official'/name)==h, ('official attachment',name)
    assert len(reference['official_sha256'])==114
    for run in RUNS:
        manifest=read(run/'generation_manifest.json')
        assert manifest['source_sha256']==reference['source_sha256']
        assert manifest['official_sha256']==reference['official_sha256']
        table=list(csv.DictReader((run/'metrics.csv').open(encoding='utf-8')))
        assert len(table)==len(manifest['jobs'])
        keyed={(r['case'],int(r['cores'])):r for r in table}
        for job in manifest['jobs']:
            case,n=job['case'],job['cores']; key=(case,n)
            assert key not in reports
            assert job['exit_code']==0 and keyed[key]['status']=='ok'
            plan=run/'plans'/f'{case}_n{n}.json'
            report=run/'plans'/f'{case}_n{n}_generation.json'
            assert sha(plan)==job['plan_sha256']==keyed[key]['plan_sha256']
            assert sha(report)==job['report_sha256']
            assert sha(PROJECT/'official/data'/f'{case}.json')==job['graph_sha256']
            r=read(report)
            assert r['official_evaluator_calls']==0
            assert r['policy']['version']=='q3-adaptive-v2-frozen'
            reports[key]=r
            locations[key]=run
            row=keyed[key]
            row={k:(v if k in ('case','status','plan_sha256','error') else float(v))
                 for k,v in row.items()}
            row['cores']=n
            assert row['l2_cycles']>0 and row['no_l2_cycles']>0
            audit=read(run/'results'/f'{case}_n{n}'/'audit.json')
            assert audit['status']=='ok' and audit['plan_sha256']==job['plan_sha256']
            for k in ('l2_cycles','no_l2_cycles','hit_bytes','miss_bytes','cache_hit_rate',
                      'l2_added_bytes','no_l2_added_bytes'):
                assert float(audit[k])==row[k], (key,k)
            assert (run/'results'/f'{case}_n{n}'/'l2.json.gz').is_file()
            assert (run/'results'/f'{case}_n{n}'/'no_l2.json.gz').is_file()
            row['selected']=r['selected']
            row['inference_seconds']=r['inference_seconds']
            row['candidate_count']=len(r['candidates'])
            rows.append(row)
    assert set(reports)=={(f'case_{i:03d}',n) for i in range(1,101) for n in range(1,6)}
    rows.sort(key=lambda r:(r['case'],r['cores']))
    by_core={}
    for n in range(1,6):
        group=[r for r in rows if r['cores']==n]
        by_core[str(n)]={k:st.mean(r[k] for r in group) for k in
            ('l2_speedup','no_l2_speedup','cache_gain','cache_hit_rate','vs_q2_gain',
             'l2_added_bytes','no_l2_added_bytes')}
        by_core[str(n)].update(cases=len(group),
            inference_median_seconds=st.median(r['inference_seconds'] for r in group),
            inference_max_seconds=max(r['inference_seconds'] for r in group),
            cache_faster=sum(r['l2_cycles']<r['no_l2_cycles'] for r in group),
            cache_equal=sum(r['l2_cycles']==r['no_l2_cycles'] for r in group),
            cache_slower=sum(r['l2_cycles']>r['no_l2_cycles'] for r in group))
    five=[r for r in rows if r['cores']==5]
    multi=[r for r in rows if r['cores']>1]
    summary=dict(version='q3-adaptive-v2-frozen',complete_cases=100,missing_jobs=0,
        paired_jobs=500,official_evaluations=1000,failed=0,source_frozen=True,
        official_files_unchanged=114,source_sha256=reference['source_sha256'],
        mean_by_cores=by_core,
        five_core_vs_q2=dict(faster=sum(r['l2_cycles']<r['q2_cycles'] for r in five),
            equal=sum(r['l2_cycles']==r['q2_cycles'] for r in five),
            slower=sum(r['l2_cycles']>r['q2_cycles'] for r in five)),
        multicores_inference=dict(median_seconds=st.median(r['inference_seconds'] for r in multi),
            maximum_seconds=max(r['inference_seconds'] for r in multi),
            median_candidates=st.median(r['candidate_count'] for r in multi),
            maximum_candidates=max(r['candidate_count'] for r in multi)),
        selection_counts_five_core=dict(Counter(r['selected'] for r in five)),
        all_added_copy_bytes_equal=all(r['l2_added_bytes']==r['no_l2_added_bytes'] for r in rows),
        input_adaptive=True,official_evaluator_in_inference=False,
        interpretation='Given cases were used for development diagnosis. Cold replay is not an unseen-distribution claim.')
    FINAL.mkdir(exist_ok=True)
    with (FINAL/'metrics.csv').open('w',encoding='utf-8',newline='') as fp:
        w=csv.DictWriter(fp,list(rows[0]));w.writeheader();w.writerows(rows)
    save(FINAL/'aggregate.json',summary)
    return rows,summary,locations

def figures(rows,summary,locations):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family':'sans-serif',
        'font.sans-serif':['Microsoft YaHei','DejaVu Sans'], 'font.size':8.5,
        'axes.labelsize':9,'axes.titlesize':10,'axes.linewidth':.65,
        'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':8,
        'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none',
        'axes.unicode_minus':False,'savefig.facecolor':'white'})
    blue,orange,gray='#205F7B','#BF7045','#67757B'
    FIGS.mkdir(exist_ok=True)
    def finish(fig,name):
        for ax in fig.axes:
            ax.spines[['top','right']].set_visible(False)
            ax.tick_params(width=.6,length=3)
        for ext in ('png','pdf','svg'):
            fig.savefig(FIGS/f'{name}.{ext}',dpi=400,bbox_inches='tight')
        plt.close(fig)
    cores=list(range(1,6)); by=summary['mean_by_cores']
    a=[by[str(n)]['no_l2_speedup'] for n in cores]
    b=[by[str(n)]['l2_speedup'] for n in cores]
    fig,axes=plt.subplots(1,2,figsize=(7.2,2.65),layout='constrained')
    ax=axes[0]
    ax.plot(cores,a,'s--',color=gray,ms=4,lw=1.2,label='同方案，无 L2')
    ax.plot(cores,b,'o-',color=blue,ms=4,lw=1.5,label='同方案，只读 L2')
    ax.plot([1,5],[1,5],':',color='#B5BABC',lw=.8,label='线性参考')
    ax.set(xlabel='核心数 N',ylabel='逐图平均加速比',xticks=cores,ylim=(.8,5.15),
           title='a  完工时间收益')
    ax.legend(loc='upper left',frameon=False)
    ax.annotate(f'{b[-1]:.3f}',(5,b[-1]),xytext=(-2,9),textcoords='offset points',ha='right',color=blue)
    ax=axes[1]
    # Exact paired equality is checked before a single curve is used.
    assert summary['all_added_copy_bytes_equal']
    movement=[by[str(n)]['l2_added_bytes']/2**20 for n in cores]
    ax.plot(cores,movement,'o-',color=orange,ms=4,lw=1.5)
    ax.set(xlabel='核心数 N',ylabel='平均额外搬运量（MiB）',xticks=cores,
           title='b  同方案的逻辑搬运量')
    ax.text(.04,.95,'开关 L2 的两组结果相同',transform=ax.transAxes,va='top',color=gray,fontsize=8)
    ax.set_ylim(0,max(movement)*1.25)
    finish(fig,'图6-5_第三问逐核收益与搬运')

    five=[r for r in rows if r['cores']==5]
    chosen=max(five,key=lambda r:(r['cache_gain'],r['case']))
    raw_path=locations[chosen['case'],5]/'results'/f"{chosen['case']}_n5"/'l2.json.gz'
    raw=json.load(gzip.open(raw_path,'rt',encoding='utf-8'))
    events=raw['cache_events'];insert=[e for e in events if e['event']=='insert']
    fig=plt.figure(figsize=(7.2,5.05),layout='constrained')
    gs=fig.add_gridspec(2,2,height_ratios=[1,1.05])
    ax=fig.add_subplot(gs[0,0])
    hit=[100*by[str(n)]['cache_hit_rate'] for n in cores]
    ax.plot(cores,hit,'o-',color=blue,ms=4,lw=1.5)
    ax.set(xlabel='核心数 N',ylabel='平均字节命中率（%）',xticks=cores,
           title='a  共享读取的复用程度',ylim=(0,max(hit)*1.22))
    ax=fig.add_subplot(gs[0,1])
    x=[100*r['cache_hit_rate'] for r in five]
    y=[100*(1-r['l2_cycles']/r['no_l2_cycles']) for r in five]
    ax.scatter(x,y,s=14,color=blue,alpha=.6,linewidths=0)
    ax.axhline(0,color=gray,lw=.65)
    ax.scatter([100*chosen['cache_hit_rate']],
        [100*(1-chosen['l2_cycles']/chosen['no_l2_cycles'])],s=32,color=orange,zorder=3)
    ax.annotate(chosen['case'],(100*chosen['cache_hit_rate'],
        100*(1-chosen['l2_cycles']/chosen['no_l2_cycles'])),
        xytext=(-4,-14),textcoords='offset points',ha='right',color=orange,fontsize=8)
    ax.set(xlabel='五核字节命中率（%）',ylabel='同方案耗时缩短率（%）',
           title='b  命中不等于关键路径收益')
    ax.text(.03,.96,'100 图；保留零收益与退步',transform=ax.transAxes,va='top',fontsize=7.5,color=gray)
    ax=fig.add_subplot(gs[1,:])
    tx=[0]+[e['time']/1000 for e in insert]+[raw['makespan']/1000]
    yy=[0]+[e['used_bytes']/2**20 for e in insert]+[raw['cache_used_bytes_final']/2**20]
    ax.step(tx,yy,where='post',color=blue,lw=1)
    ax.fill_between(tx,yy,step='post',alpha=.09,color=blue)
    ax.axhline(raw['cache_capacity_bytes']/2**20,color=gray,ls='--',lw=.8)
    ev=[e for e in insert if e['evicted_tensor_ids']]
    ax.scatter([e['time']/1000 for e in ev],[-.06]*len(ev),marker='|',s=18,lw=.65,color=orange)
    ax.text(.99,.92,'容量 1 MiB',transform=ax.transAxes,ha='right',fontsize=8,color=gray)
    ax.text(.99,.23,'下方橙色短线：发生 FIFO 淘汰的插入事件',
            transform=ax.transAxes,ha='right',fontsize=7.5,color=orange)
    ax.set(xlabel='执行时间（千 cycle）',ylabel='L2 驻留量（MiB）',ylim=(-.13,1.13),
           xlim=(0,raw['makespan']/1000),
           title=f"c  {chosen['case']}：五核缓存收益最大用例的完整 FIFO 轨迹")
    finish(fig,'图6-6_第三问缓存复用与时序')
    save(FINAL/'figure_sources.json',dict(
        primary='metrics.csv',all_cases=100,core_counts=cores,
        mechanism_case=chosen['case'],selection='maximum paired cache_gain among all 100 five-core cases',
        mechanism_source=str(raw_path.relative_to(PROJECT)),raw_sha256=sha(raw_path),
        insert_events=len(insert),evicting_insert_events=len(ev),
        aggregation='arithmetic mean of per-case ratios; no confidence intervals',
        event_downsampling=False))
    return chosen

def paper(summary,chosen):
    path=PROJECT/'论文第六章/问题三建模与求解.tex'
    by=summary['mean_by_cores'];five=by['5'];runtime=summary['multicores_inference']
    lines=[r'最终版本对全部 $100$ 图、$1\sim5$ 核重新生成 $500$ 份方案，',
        r'冻结后进行 $1000$ 次开关 L2 的配对官方验收，全部通过。',
        r'验收前后核对了 $114$ 份原始附件和全部求解文件的字节哈希；',
        r'正式代码包只含输入图求解代码与全局配置，不含历史方案或官方评估器。',
        r'表~\ref{tab:q3-results} 中的每项均为 $100$ 个逐图指标的算术平均，',
        r'并非总时间之比。',r'\begin{table}[htbp]\centering',
        r'\caption{第三问全量配对结果。无 L2 与 L2 使用同一份冻结方案。}',
        r'\label{tab:q3-results}',r'\begin{tabular}{rrrrr}\hline',
        r'$N$ & $\overline S^{0}_N$ & $\overline S^{L2}_N$ & $\overline R_N$ & 字节命中率 (\%)\\\hline']
    for n in range(1,6):
        d=by[str(n)]
        lines.append(f"{n} & {d['no_l2_speedup']:.6f} & {d['l2_speedup']:.6f} & {d['cache_gain']:.6f} & {100*d['cache_hit_rate']:.2f}"+r'\\')
    lines += [r'\hline\end{tabular}\end{table}',
        f"五核平均加速比为 ${five['l2_speedup']:.6f}$，高于第二问固定算法的 $3.952170$；",
        r'总体改善不意味着每一图均占优，故同时保留逐例比较。',
        f"在逐图比较中，相对第二问有 {summary['five_core_vs_q2']['faster']} 图改善、",
        f"{summary['five_core_vs_q2']['equal']} 图相同、{summary['five_core_vs_q2']['slower']} 图退步。",
        r'该比较混合了调度与硬件收益；同方案缓存对照的五核平均比值为',
        f"$\\overline R_5={five['cache_gain']:.6f}$，二者不可相互替代。",
        f"开关缓存的五核对照中，{five['cache_faster']} 图缩短、{five['cache_equal']} 图相同、",
        f"{five['cache_slower']} 图变慢。缓存改变了共享带宽服务和指令完成次序，",
        r'因此它不构成对所有图的单调加速保证。',
        r'\begin{figure}[htbp]\centering',
        r'\includegraphics[width=\linewidth]{论文第六章/figures/图6-5_第三问逐核收益与搬运.pdf}',
        r'\caption{全量逐核结果。左图比较同方案开启与关闭 L2 的加速比，点为逐图算术均值；',
        r'右图为官方额外搬运量。全部配对中该逻辑字节指标相同，因此只绘一条曲线；',
        r'这不表示 DDR 实际服务字节相同。单核只采用固定整图方案。}',
        r'\label{fig:q3-scaling}\end{figure}',
        r'图~\ref{fig:q3-cache} 将字节命中率与完工时间变化分开呈现。',
        r'五核散点保留全部用例，命中率高而收益小的点表明，命中率不足以单独预测总体收益。',
        '完整 FIFO 轨迹选取缓存配对收益最大的用例 '+r'\texttt{'+chosen['case'].replace('_',r'\_')+r'}，',
        r'其选择依据预先写入绘图脚本，不用该用例替代总体结论。',
        r'\begin{figure}[htbp]\centering',
        r'\includegraphics[width=\linewidth]{论文第六章/figures/图6-6_第三问缓存复用与时序.pdf}',
        r'\caption{缓存机理与真实时序。a 为各核数的平均字节命中率；b 为全部 $100$ 图的五核配对关系；',
        r'c 直接重放缓存收益最大用例的官方插入事件，橙色短线标记伴随淘汰的插入。',
        r'事件未下采样，驻留曲线在插入完成时变化；没有人为指定预热或起始时刻。}',
        r'\label{fig:q3-cache}\end{figure}',
        f"在本机四工作进程并发实验中，$2\\sim5$ 核共 $400$ 次独立求解的中位耗时为",
        f"${runtime['median_seconds']:.3f}$ s，最长为 ${runtime['maximum_seconds']:.3f}$ s；",
        f"去重后候选数中位数为 ${runtime['median_candidates']:g}$、最大为 ${runtime['maximum_candidates']}$。",
        r'这些时间来自进程内计时，包含图读取、构造和模型比较，不含进程启动与官方验收，',
        r'也不是专用设备上的串行性能测试。模型以固定规模的构造代替反复试跑官方评估器，',
        r'速度和可独立执行性由此获得，代价是保留了局部顺序与换出量近似的误差。']
    text=path.read_text(encoding='utf-8');start='% Q3_RESULTS_BEGIN';end='% Q3_RESULTS_END'
    before,rest=text.split(start,1);_,after=rest.split(end,1)
    path.write_text(before+start+'\n'+'\n'.join(lines)+'\n'+end+after,encoding='utf-8')

if __name__=='__main__':
    rows,summary,locations=aggregate()
    chosen=figures(rows,summary,locations)
    paper(summary,chosen)
    print(json.dumps(summary,ensure_ascii=False))
