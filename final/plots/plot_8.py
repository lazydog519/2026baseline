"""Chapter 8 figures and tables, rebuilt only from frozen evaluation records."""
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
import statistics as st

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT
INK, GRAY, LIGHT = '#171717', '#6c6c6c', '#c5c5c5'


def write_csv(name, rows):
    with (ROOT / 'data' / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save(fig, stem):
    stem=json.loads((ROOT/'data/figure_names.json').read_text(encoding='utf-8'))[stem]
    for ext in ('png', 'pdf'):
        fig.savefig(ROOT / 'figures' / f'{stem}.{ext}', dpi=400,
                    bbox_inches='tight', pad_inches=.045)
    plt.close(fig)


def panel(ax, letter, title):
    ax.set_title(title, loc='left', fontsize=9, pad=10)
    ax.text(-.13, 1.055, letter, transform=ax.transAxes, fontweight='bold', fontsize=11)


def clean(ax):
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(direction='out', width=.65, length=3)
    ax.grid(axis='y', color='#e6e6e6', linewidth=.5)
    ax.set_axisbelow(True)


def pathway():
    fig, ax = plt.subplots(figsize=(7.0, 3.7))
    ax.set(xlim=(0, 10), ylim=(0, 5.9))
    ax.axis('off')
    def box(x, y, w, h, text, fill='white'):
        ax.add_patch(Rectangle((x, y), w, h, facecolor=fill, edgecolor=INK, linewidth=.8))
        ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=8.2, linespacing=1.45)
    def arrow(a, b, label=None, offset=(0,0), style='-'):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle='-|>', mutation_scale=8,
                                    linewidth=.8, color=INK, linestyle=style))
        if label:
            ax.text((a[0]+b[0])/2+offset[0], (a[1]+b[1])/2+offset[1], label,
                    ha='center', va='center', fontsize=7.7,
                    bbox=dict(facecolor='white', edgecolor='none', pad=.7))
    ax.text(0,5.65,'a', fontsize=11, weight='bold')
    ax.text(.35,5.65,'读写路径：请求发射时确定带宽池', fontsize=9)
    box(0,3.70,1.25,.62,'COPY_IN')
    box(1.8,3.70,1.5,.62,'逻辑张量查询')
    box(4.2,4.60,2.15,.68,'共享 FIFO L2\n250 byte/cycle', '#f0f0f0')
    box(4.2,2.82,2.15,.68,'DDR\n60 byte/cycle')
    box(7.35,3.70,2.45,.62,'核内 L1 / UB → 计算')
    arrow((1.25,4.01),(1.8,4.01))
    arrow((3.3,4.10),(4.2,4.89),'命中',(0,.20))
    arrow((3.3,3.86),(4.2,3.17),'未命中',(0,-.22))
    arrow((6.35,4.9),(7.35,4.12))
    arrow((6.35,3.18),(7.35,3.88))
    arrow((8.7,3.70),(6.35,3.02),'COPY_OUT 写回',(.25,-.24))
    ax.text(.02,2.42,'各核心共享总带宽；同一池内在途请求均分，两个池独立计时。', fontsize=8)
    ax.plot([0,9.8],[2.12,2.12], color=LIGHT, linewidth=.7)
    ax.text(0,1.79,'b', fontsize=11, weight='bold')
    ax.text(.35,1.79,'读取完成：检查插入条件，必要时从队首淘汰', fontsize=9)
    for j, label in enumerate([r'$q_1$',r'$q_2$',r'$\cdots$',r'$q_m$']):
        box(2.1+j*.96,.66,.96,.54,label, '#f0f0f0' if j==0 else 'white')
    box(7.45,.66,1.65,.54,r'新条目 $\tau_e$', '#f0f0f0')
    arrow((7.45,.93),(6.0,.93),'尾部插入',(0,.27))
    arrow((2.1,.93),(.48,.93),'空间不足时淘汰',(0,.28))
    ax.text(4.0,.18,'容量 1 MiB；已有条目保持原次序，命中不刷新 FIFO。',
            ha='center', fontsize=8)
    save(fig,'图8-1_共享Cache数据通路')


def performance(rows, summary):
    means = summary['mean_by_cores']
    ns = np.arange(1,6)
    # Derive Q2 means from the corresponding official rows, independent of summary schema.
    with (ROOT/'data/q2_metrics.csv').open(encoding='utf-8-sig') as f:
        q2rows=list(csv.DictReader(f))
    speedkey=next(k for k in q2rows[0] if k in ('speedup','speedup_vs_single'))
    q2mean=[1.]+[st.mean(float(r[speedkey]) for r in q2rows if int(r['cores'])==n) for n in ns[1:]]
    fig=plt.figure(figsize=(7,3.55))
    gs=fig.add_gridspec(2,2,width_ratios=[1.3,1],hspace=.67,wspace=.47)
    ax=fig.add_subplot(gs[:,0]); clean(ax)
    ax.plot(ns,q2mean,'^--',color=GRAY,lw=1,ms=4,label='问题二')
    ax.plot(ns,[means[str(n)]['no_l2_speedup'] for n in ns],'s:',color=INK,lw=1,ms=4,mfc='white',label='问题三，关闭 L2')
    ax.plot(ns,[means[str(n)]['l2_speedup'] for n in ns],'o-',color=INK,lw=1.25,ms=4,label='问题三，开启 L2')
    ax.set(xticks=ns,xlabel='核心数 $N$',ylabel='平均加速比',ylim=(.88,4.5))
    ax.legend(frameon=False,fontsize=7.5,loc='upper left',handlelength=2.3)
    panel(ax,'a','整体调度性能')
    ax.annotate('4.1939',xy=(5,means['5']['l2_speedup']),xytext=(-34,10),textcoords='offset points',fontsize=8)
    ax=fig.add_subplot(gs[0,1]); clean(ax)
    ax.plot(ns,[means[str(n)]['l2_added_bytes']/2**20 for n in ns],'o-',color=INK,lw=1,ms=3.5)
    ax.set(xticks=ns,ylabel='额外搬运 / MiB',ylim=(0,13))
    panel(ax,'b','逻辑搬运量（开关 L2 相同）')
    ax=fig.add_subplot(gs[1,1]);clean(ax)
    ax.plot(ns,[means[str(n)]['cache_hit_rate']*100 for n in ns],'s-',color=GRAY,lw=1,ms=3.5,mfc='white')
    ax.set(xticks=ns,xlabel='核心数 $N$',ylabel='字节命中率 / %',ylim=(0,32))
    panel(ax,'c','读取命中比例')
    save(fig,'图8-2_逐核性能与搬运')
    table=[]
    for n in ns:
        m=means[str(n)]
        table.append(dict(cores=int(n),q2_speedup=q2mean[n-1],no_l2_speedup=m['no_l2_speedup'],
            l2_speedup=m['l2_speedup'],cache_gain=m['cache_gain'],
            byte_hit_percent=100*m['cache_hit_rate'],added_mib=m['l2_added_bytes']/2**20))
    write_csv('问题三逐核统计.csv',table)
    return table


def windows(rows):
    five=[r for r in rows if int(r['cores'])==5]
    best=max(five,key=lambda r:float(r['cache_gain']))
    case=best['case']
    path=ROOT/'data'/f'{case}_n5_l2.json.gz'
    with gzip.open(path,'rt',encoding='utf-8') as f:
        raw=json.load(f)
    events=raw['cache_events']
    inserts=Counter(e['tensor_id'] for e in events if e['event']=='insert')
    hits=Counter(e['tensor_id'] for e in events if e['event']=='hit')
    tids=sorted((t for t,v in inserts.items() if v>=2),key=lambda t:(-inserts[t],-hits[t],-int(t)))[:3]
    assert len(tids)==3
    index={t:i for i,t in enumerate(tids)}
    intervals={t:[] for t in tids}; live={}; trace=[]
    for order,e in enumerate(events):
        tm=float(e['time']);tid=e['tensor_id']
        for evicted in e.get('evicted_tensor_ids',[]):
            if evicted in live:
                intervals[evicted].append((live.pop(evicted),tm))
                trace.append(dict(case=case,event_order=order,tensor_id=evicted,alias=f'tau_{index[evicted]+1}',
                    time=tm,event='evict',core_id=e.get('core_id',''),op_id=e.get('op_id','')))
        if tid in index:
            trace.append(dict(case=case,event_order=order,tensor_id=tid,alias=f'tau_{index[tid]+1}',
                time=tm,event=e['event'],core_id=e.get('core_id',''),op_id=e.get('op_id','')))
            if e['event']=='insert':
                assert tid not in live
                live[tid]=tm
    for tid,start in live.items():
        intervals[tid].append((start,float(best['l2_cycles'])))
    write_csv('FIFO驻留事件.csv',trace)
    write_csv('FIFO驻留窗口.csv',[dict(case=case,tensor_id=t,alias=f'tau_{i+1}',start_cycle=a,end_cycle=b)
        for i,t in enumerate(tids) for a,b in intervals[t]])
    fig=plt.figure(figsize=(7,4.25))
    gs=fig.add_gridspec(2,1,height_ratios=[1.65,1],hspace=.70)
    ax=fig.add_subplot(gs[0]);clean(ax)
    xx=[100*float(r['cache_hit_rate']) for r in five]
    yy=[100*(1-float(r['l2_cycles'])/float(r['no_l2_cycles'])) for r in five]
    ax.scatter(xx,yy,s=18,facecolors='white',edgecolors=GRAY,linewidths=.75)
    ax.axhline(0,color=INK,lw=.7)
    ax.set(xlabel='字节命中率 / %',ylabel='耗时缩短率 / %',xlim=(-1.5,78),ylim=(-3.2,43))
    panel(ax,'a','命中率与同方案缓存收益：五核，100 图')
    for ident,offset in [('case_080',(9,-4)),('case_030',(-68,15)),('case_092',(-67,26))]:
        r=next(r for r in five if r['case']==ident)
        point=(float(r['cache_hit_rate'])*100,100*(1-float(r['l2_cycles'])/float(r['no_l2_cycles'])))
        ax.scatter(*point,s=24,c=INK,zorder=5)
        ax.annotate(ident,point,xytext=offset,textcoords='offset points',fontsize=7.5,
                    arrowprops=dict(arrowstyle='-',color=GRAY,lw=.65))
    ax=fig.add_subplot(gs[1]);clean(ax)
    for i,tid in enumerate(tids):
        for a,b in intervals[tid]:
            ax.broken_barh([(a/1000,(b-a)/1000)],(i-.14,.28),facecolor=LIGHT,edgecolor=INK,linewidth=.55)
        for event,marker in [('hit','o'),('miss','x')]:
            times=[r['time']/1000 for r in trace if r['tensor_id']==tid and r['event']==event]
            ax.scatter(times,[i]*len(times),marker=marker,s=22,color=INK,linewidths=.8,zorder=4,
                label={'hit':'命中','miss':'未命中'}[event] if i==0 else None)
    ax.set(yticks=range(3),yticklabels=[r'$\tau_1$',r'$\tau_2$',r'$\tau_3$'],
           ylim=(-.55,2.55),xlim=(-1,float(best['l2_cycles'])/1000),xlabel='执行时间 / $10^3$ cycle')
    ax.invert_yaxis();ax.grid(False)
    panel(ax,'b',f'{case}：重复插入张量的实际 FIFO 驻留窗口')
    ax.legend(frameon=False,ncol=2,loc='upper right',bbox_to_anchor=(1,1.31),fontsize=7.5)
    save(fig,'图8-3_命中收益与驻留窗口')
    return dict(source=str(path.relative_to(PROJECT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        selected_case=case,selected_tensors=tids,selection_rule='descending insertion count, hit count, tensor id; insertions >= 2',
        raw_events=len(events),plotted_intervals=sum(map(len,intervals.values())))


def main():
    plt.rcParams.update({'font.family':['SimSun','DejaVu Serif'], 'font.size':8.5,
        'axes.labelsize':8.5,'axes.linewidth':.7,'xtick.labelsize':8,'ytick.labelsize':8,
        'mathtext.fontset':'stix','pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'path',
        'axes.unicode_minus':False,'savefig.facecolor':'white'})
    for d in ('data','figures'):(ROOT/d).mkdir(exist_ok=True)
    metrics=ROOT/'data/问题三逐例配对结果.csv'
    with metrics.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    summary=json.loads((ROOT/'data/q3_aggregate.json').read_text('utf-8'))
    assert len(rows)==len({(r['case'],r['cores']) for r in rows})==500
    assert all(r['status']=='ok' for r in rows)
    assert all(r['selected']!='single_active_core_fallback' for r in rows)
    assert all(float(r['l2_added_bytes'])==float(r['no_l2_added_bytes']) for r in rows)
    for n in range(1,6):
        subset=[r for r in rows if int(r['cores'])==n]
        assert len(subset)==100
        for k in ('l2_speedup','no_l2_speedup','cache_gain','cache_hit_rate','l2_added_bytes'):
            assert abs(st.mean(float(r[k]) for r in subset)-summary['mean_by_cores'][str(n)][k])<1e-8
    write_csv('问题三逐例配对结果.csv',rows)
    pathway()
    table=performance(rows,summary)
    trace=windows(rows)
    audit=dict(paired_jobs=500,official_evaluations=1000,all_added_copy_bytes_equal=True,
        means_recomputed=True,metrics_sha256=hashlib.sha256(metrics.read_bytes()).hexdigest(),
        trace=trace,display_table=table,figures=3,formats=['png','pdf'],
        statement='Figures use frozen official records. Schematic in Fig 8-1 is not a measured trace.')
    (ROOT/'data/图8数据核对.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n','utf-8')
    print('Figures 8-1–8-3 rebuilt from frozen data.')


if __name__=='__main__':main()
