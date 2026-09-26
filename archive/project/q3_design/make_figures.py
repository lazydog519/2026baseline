"""Two evidence figures. Adapted from mathodology F05/F07/F15 principles.

Paired configuration effects use matched plans; FIFO is shown as exact event
intervals rather than interpolated heatmaps. No generated or synthetic results.
"""
import csv
import gzip
import json
from collections import Counter
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'figures'
COLORS = {1:'#687887', 2:'#276C98', 5:'#BA663D'}
MARKERS = {1:'o', 2:'s', 5:'^'}


def save(fig, name):
    for ext in ('png', 'pdf'):
        fig.savefig(OUT/f'{name}.{ext}', dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def main():
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':'Microsoft YaHei', 'font.size':9,
        'axes.titlesize':10, 'axes.labelsize':9, 'axes.spines.top':False,
        'axes.spines.right':False, 'axes.unicode_minus':False, 'pdf.fonttype':42,
        'axes.edgecolor':'#777777', 'xtick.color':'#444444', 'ytick.color':'#444444'})
    rows=[]
    for phase in ('development','confirmation','diagnostic'):
        with (ROOT/phase/'metrics.csv').open(encoding='utf-8') as f:
            for r in csv.DictReader(f):
                rows.append(dict(phase=phase,case=r['case'],cores=int(r['cores']),
                    hit_percent=100*float(r['hit_rate']),
                    cache_speedup_percent=100*(float(r['paired_cache_ratio'])-1),
                    with_l2_cycles=int(r['with_l2_cycles']),
                    no_l2_cycles=int(r['same_plan_no_l2_cycles'])))
    with (OUT/'paired_effects.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    order=['case_036','case_082','case_100','case_008','case_074','case_095','case_044']
    labels=['036  开发','082  开发','100  开发','008  确认','074  确认','095  确认','044  诊断']
    fig,(a,b)=plt.subplots(1,2,figsize=(8.1,4.4),gridspec_kw={'width_ratios':[1,1.15]})
    fig.subplots_adjust(left=.12,right=.97,bottom=.19,top=.86,wspace=.35)
    for r in rows:
        n=r['cores'];delta={1:-.19,2:0,5:.19}[n]
        a.scatter(r['cache_speedup_percent'],order.index(r['case'])+delta,
                  marker=MARKERS[n],s=28,color=COLORS[n],zorder=3)
        b.scatter(r['hit_percent'],r['cache_speedup_percent'],marker=MARKERS[n],
                  s=34,color=COLORS[n],alpha=.85,zorder=3)
    for y in [2.5,5.5]:a.axhline(y,color='#D3D5D6',lw=.7)
    a.axvline(0,color='#999999',lw=.8)
    a.set(yticks=range(7),yticklabels=labels,ylim=(6.5,-.55),xlim=(-.7,13),
          xlabel='同方案加速增幅  (R − 1) × 100%')
    a.set_title('(a) 同一方案，有 / 无 L2 配对',loc='left',pad=13)
    b.set(xlabel='字节命中率 H (%)',ylabel='同方案加速增幅 (%)',xlim=(-2,44),ylim=(-.6,13))
    b.set_title('(b) 命中率与完成时间收益',loc='left',pad=13)
    b.axhline(0,color='#999999',lw=.8)
    annotations={('case_044',2):('044 / 2 核\n11.752%',(21,10.7)),
                 ('case_074',5):('074 / 5 核\n2.230%',(19,4.5)),
                 ('case_082',5):('082 / 5 核\n命中 38.19%，增幅 0%',(17,1.3))}
    for r in rows:
        key=(r['case'],r['cores'])
        if key in annotations:
            label,position=annotations[key]
            b.annotate(label,(r['hit_percent'],r['cache_speedup_percent']),xytext=position,
                       fontsize=8,arrowprops=dict(arrowstyle='-',lw=.7,color='#555555'))
    handles=[Line2D([],[],marker=MARKERS[n],color=COLORS[n],linestyle='',label=f'{n} 核',markersize=5) for n in (1,2,5)]
    fig.legend(handles=handles,loc='upper center',ncol=3,frameon=False,bbox_to_anchor=(.53,1.0))
    fig.text(.12,.045,'7 个算例 × 3 种核数；同一算例的不同核数并非独立样本。散点中的相同数值会重合。',fontsize=8,color='#555555')
    save(fig,'01_paired_cache_effect')

    source=ROOT/'confirmation/case_074/n5/selected_result.json.gz'
    with gzip.open(source,'rt',encoding='utf-8') as f:result=json.load(f)
    windows=[]
    with (ROOT/'cache_windows.csv').open(encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['case']=='case_074' and r['cores']=='5':windows.append(r)
    counts=Counter(int(r['tensor_id']) for r in windows)
    hits=Counter(e['tensor_id'] for e in result['cache_events'] if e['event']=='hit')
    misses=Counter(e['tensor_id'] for e in result['cache_events'] if e['event']=='miss')
    # Show two actual DDR fills and subsequent reuse, avoiding nearly touching
    # episodes caused by an in-flight hit being evicted and then reinserted.
    tid=min((t for t in counts if counts[t]>=2 and hits[t] and misses[t]>=2),key=lambda t:(-hits[t],t))
    chosen=[r for r in windows if int(r['tensor_id'])==tid]
    fig,(a,b,c)=plt.subplots(3,1,figsize=(8.1,5.3),sharex=True,
         gridspec_kw={'height_ratios':[.75,2.2,1.1]})
    fig.subplots_adjust(left=.14,right=.97,bottom=.13,top=.87,hspace=.24)
    for w in chosen:
        start,end=int(w['start_cycle'])/1000,int(w['end_cycle'])/1000
        a.broken_barh([(start,end-start)],(.25,.5),facecolors='#B7D6CE',edgecolors='#398071',lw=.8)
        a.plot(end,.5,marker='x',color='#AF5942',ms=6)
        a.text((start+end)/2,.98,f'{start:.3f}–{end:.3f}',ha='center',fontsize=7.5)
    a.set(yticks=[.5],yticklabels=['驻留窗口'],ylim=(0,1.5))
    a.set_title(f'case 074，5 核：逻辑张量 {tid} 的 FIFO 驻留与读取',loc='left',pad=18)
    events=[]
    lookup={(core['core_id'],op['op_id']):op for core in result['per_core_timeline'] for op in core['ops']}
    for i,e in enumerate(result['cache_events']):
        if e['tensor_id']!=tid or e['event'] not in ('hit','miss'):continue
        op=lookup[e['core_id'],e['op_id']];hit=e['event']=='hit'
        b.scatter(e['time']/1000,e['core_id'],marker='o' if hit else 'x',
                  color='#276C98' if hit else '#AF5942',s=35,zorder=4)
        b.text(e['time']/1000+3,e['core_id']-.22,f"{op['end']-op['start']} cycles",fontsize=7.5)
        events.append(dict(event_index=i,tensor_id=tid,core=e['core_id'],
            event=e['event'],start=e['time'],end=op['end'],memory_path=op['memory_path']))
    for y in range(5):b.axhline(y,color='#E1E3E5',lw=.6,zorder=0)
    b.set(yticks=range(5),yticklabels=[f'Core {i}' for i in range(5)],ylim=(4.7,-.7))
    t=[0];used=[0]
    for e in result['cache_events']:
        if e['event']=='insert':t.append(e['time']/1000);used.append(e['used_bytes']/1048576)
    t.append(result['makespan']/1000);used.append(used[-1])
    c.step(t,used,where='post',color='#687887',lw=.85)
    c.axhline(1,ls=':',color='#AF5942',lw=.8)
    c.set(ylabel='总 L2 占用 (MiB)',xlabel='模拟时间 (10³ cycles)',ylim=(-.03,1.1),xlim=(0,result['makespan']/1000))
    legend=[Line2D([],[],marker='o',color='#276C98',linestyle='',label='发射时命中'),
            Line2D([],[],marker='x',color='#AF5942',linestyle='',label='发射时未命中 / 窗口终点淘汰')]
    fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.56,1.0),ncol=2,frameon=False,fontsize=8)
    save(fig,'02_fifo_residence_window')
    (OUT/'fifo_example.json').write_text(json.dumps(dict(case='case_074',cores=5,
        tensor_id=tid,selection='Most hits among tensors with at least two residence episodes and two misses; tie by tensor ID.',
        windows=chosen,accesses=events),indent=2)+'\n',encoding='utf-8')
    print('Created exactly two PNG/PDF figure pairs from recorded official results.')


if __name__=='__main__':main()
