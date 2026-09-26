"""Recompute manuscript statistics and figures from frozen records; no evaluator calls."""
from pathlib import Path
import csv, json, hashlib, statistics, shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
R=Path(__file__).resolve().parent
P=R.parent
MIB=2**20
plt.rcParams.update({'font.family':['SimSun','DejaVu Serif'],'font.size':8.5,
                     'axes.unicode_minus':False,'mathtext.fontset':'stix',
                     'axes.linewidth':.65,'pdf.fonttype':42,'ps.fonttype':42})
def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(name,rr):
    with (R/'data'/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rr[0]));w.writeheader();w.writerows(rr)
def save(fig,name):
    for ext in ['png','pdf','svg']:fig.savefig(R/'figures'/f'{name}.{ext}',dpi=400,bbox_inches='tight',pad_inches=.07)
    plt.close(fig)
def tidy(ax):
    ax.spines[['top','right']].set_visible(False)
    ax.tick_params(direction='out',width=.65,length=3)
    ax.grid(axis='y',color='.9',lw=.5);ax.set_axisbelow(True)
def label(ax,letter,title):
    ax.set_title(title,loc='left',pad=11,fontsize=9)
    ax.text(-.13,1.075,letter,transform=ax.transAxes,weight='bold',fontsize=11)
def box(ax,x,y,w,h,t,fc='white',fs=8.5):
    ax.add_patch(Rectangle((x,y),w,h,facecolor=fc,edgecolor='.15',lw=.8))
    ax.text(x+w/2,y+h/2,t,ha='center',va='center',fontsize=fs,linespacing=1.55)
def arrow(ax,a,b):
    ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=9,lw=.8,color='.2'))

rr=rows(R/'data/输入图结构统计.csv')
assert len(rr)==100 and len({r['case'] for r in rr})==100
for r in rr:
    raw=P/'official/data'/(r['case']+'.json')
    assert hashlib.sha256(raw.read_bytes()).hexdigest()==r['sha256'],r['case']
ab=rows(R/'data/两场景逐例结果.csv')
assert len(ab)==400 and len({(r['case'],r['cores']) for r in ab})==400
q3=rows(P/'q3_adaptive_20260926/final/metrics.csv')
assert len(q3)==500 and all(r['status']=='ok' for r in q3)
frozen=json.loads((R/'data/三问冻结版本核对.json').read_text(encoding='utf-8'))
for key,d in [('q1','q1_priority_20260926'),('q2','q2_priority_20260926/final_v2'),('q3','q3_adaptive_20260926')]:
    for f,sha in frozen[key]['source_sha256'].items():
        assert hashlib.sha256((P/d/f).read_bytes()).hexdigest()==sha,(key,f)
stats={}
for k in ['compute_ops','dag_edges','weak_components','graph_depth_ops','compute_cycles','critical_path_cycles','work_span_parallelism','largest_component_fraction']:
    v=[float(r[k]) for r in rr];stats[k]={'min':min(v),'median':statistics.median(v),'max':max(v)}
stats['shared_input_cases']=sum(int(r['shared_input_tensors'])>0 for r in rr)
stats['multi_component_cases']=sum(int(r['weak_components'])>1 for r in rr)
stats['multi_at_least_five']=all(int(r['weak_components'])>=5 for r in rr if int(r['weak_components'])>1)

fig,ax=plt.subplots(figsize=(7,4.0));ax.set(xlim=(0,10),ylim=(0,6.2));ax.axis('off')
box(ax,0,4.8,2.15,1.12,'当前输入图\n依赖 · 张量 · 管道',fs=7.7)
box(ax,2.8,4.8,3.1,1.12,'一次性结构分析\n分量 · 层宽 · 共享输入')
box(ax,6.65,4.8,3.3,1.12,'当前图上的有限构造\n切分 · 分核 · 子图排序')
arrow(ax,(2.15,5.36),(2.8,5.36));arrow(ax,(5.9,5.36),(6.65,5.36))
for x,t in [(0,'问题一：Task 边界\n工作量 + 依赖 + 搬运'),(3.55,'问题二：同核复用\n通信 + 生命周期风险'),(7.1,'问题三：共享读取\nFIFO + 双池事件时序')]:
    box(ax,x,2.55,2.85,1.25,t,fc='.95',fs=8.3)
arrow(ax,(2.85,3.18),(3.55,3.18));arrow(ax,(6.4,3.18),(7.1,3.18))
ax.plot([8.3,8.3],[4.8,4.17],color='.2',lw=.8)
ax.plot([1.42,8.52],[4.17,4.17],color='.2',lw=.8)
for x in [1.42,4.97,8.52]:arrow(ax,(x,4.17),(x,3.8))
ax.text(4.8,4.43,'同一输出接口，按场景选择评价机制',ha='center',fontsize=8)
box(ax,0,.55,3,1.05,'生成并保存一个方案\n记录版本与方案摘要')
box(ax,3.6,.55,2.9,1.05,'独立官方验收\n时间 · 搬运 · 命中')
box(ax,7.1,.55,2.85,1.05,'逐图对照与解释\n改善 · 退步 · 模型误差')
for x in [1.42,4.97,8.52]:ax.plot([x,x],[2.55,2.28],color='.2',lw=.8)
ax.plot([1.42,8.52],[2.28,2.28],color='.2',lw=.8)
arrow(ax,(1.42,2.28),(1.42,1.60));arrow(ax,(3,1.08),(3.6,1.08));arrow(ax,(6.5,1.08),(7.1,1.08))
ax.plot([0,10],[2.12,2.12],color='.6',ls='--',lw=.65)
ax.text(9.9,1.86,'验收结果不回流至本次方案选择',ha='right',fontsize=8)
save(fig,'图2-1_模型递进与证据链')

fig,axs=plt.subplots(1,3,figsize=(7.3,2.9),layout='constrained')
for multi,marker,fill in [(False,'o','white'),(True,'o','.3')]:
    sub=[r for r in rr if (int(r['weak_components'])>1)==multi]
    for ax,x,y in [(axs[0],'compute_ops','graph_depth_ops'),(axs[1],'weak_components','largest_component_fraction'),(axs[2],'critical_path_cycles','compute_cycles')]:
        ax.scatter([float(r[x]) for r in sub],[float(r[y]) for r in sub],s=17,marker=marker,facecolor=fill,edgecolor='.2',lw=.6,label='多分量（84）' if multi else '单分量（16）')
for ax in axs:ax.set_xscale('log');tidy(ax)
axs[0].set_yscale('log');axs[2].set_yscale('log')
axs[0].set(xlabel='非 COPY 操作数',ylabel='拓扑深度 / 层')
axs[1].set(xlabel='弱连通分量数',ylabel='最大分量节点占比',ylim=(-.03,1.06))
axs[2].set(xlabel='计算关键路径 / cycle',ylabel='总工作量 / cycle')
xs=np.geomspace(400,863040,50)
axs[2].plot(xs,xs,color='.65',lw=.65,ls=':',label='W=L');axs[2].plot(xs,5*xs,color='.65',lw=.65,ls='--',label='W=5L')
axs[2].legend(handles=axs[2].lines,frameon=False,fontsize=7,loc='upper left')
for a,l,t in zip(axs,'abc',['规模与纵向依赖','分量与集中程度','工作量与计算路径']):label(a,l,t)
axs[0].legend(frameon=False,fontsize=7,loc='upper left')
save(fig,'图5-1_输入图结构与资源特征')

stat=json.loads((R/'data/统计摘要.json').read_text(encoding='utf-8'))
fig,axs=plt.subplots(1,2,figsize=(7,2.8),layout='constrained')
n=np.arange(1,6)
axs[0].plot(n,[1]+[stat['A'][str(i)]['mean'] for i in range(2,6)],'o-',color='.15',ms=4,lw=1.3)
axs[0].set(xticks=n,xlabel='核心数',ylabel='平均加速比',ylim=(.8,4.2))
for x,y in zip(n,[1]+[stat['A'][str(i)]['mean'] for i in range(2,6)]):axs[0].annotate(f'{y:.2f}',(x,y),xytext=(0,8),textcoords='offset points',ha='center',fontsize=7)
profiles={r['case']:r for r in rr}
groups=[[float(r['A_speedup']) for r in ab if r['cores']=='5' and (int(profiles[r['case']]['weak_components'])>1)==mul] for mul in [False,True]]
axs[1].boxplot(groups,tick_labels=['单分量（16）','多分量（84）'],widths=.45,patch_artist=True,boxprops={'facecolor':'.87'},medianprops={'color':'black'},flierprops={'marker':'o','markersize':3,'markerfacecolor':'white'})
axs[1].set(ylabel='五核加速比')
for a,l,t in zip(axs,'ab',['随核心数的变化','按计算连通性分组']):tidy(a);label(a,l,t)
save(fig,'图6-1_问题一求解结果')

comp={r['case']:r for r in rows(P/'q1_priority_20260926/component_comparator.csv') if r['cores']=='5'}
paired=[]
for r in ab:
    if r['cores']!='5':continue
    t=float(r['A_makespan_cycles']);ref=float(comp[r['case']]['component_cycles'])
    paired.append({'case':r['case'],'component_cycles':ref,'selected_cycles':t,'reduction_percent':100*(1-t/ref)})
write('问题一分量对照.csv',paired)
yy=sorted(x['reduction_percent'] for x in paired)
fig,ax=plt.subplots(figsize=(7,2.45),layout='constrained')
ax.bar(np.arange(1,101),yy,color=['.15' if y>=0 else '.6' for y in yy],width=.9)
ax.axhline(0,color='black',lw=.7);tidy(ax)
ax.set(xlabel='按耗时改善幅度排序后的图序号',ylabel='耗时缩短率 / %',xlim=(0,101))
ax.text(.02,.95,'38 改善  ·  60 不变  ·  2 退步',transform=ax.transAxes,va='top',fontsize=9)
save(fig,'图6-2_结构候选的逐图对照')
stats['component_comparison']={'faster':sum(v['reduction_percent']>0 for v in paired),'slower':sum(v['reduction_percent']<0 for v in paired),'equal':sum(v['reduction_percent']==0 for v in paired)}

fig,ax=plt.subplots(figsize=(7,3.15));ax.set(xlim=(0,10),ylim=(0,4.6));ax.axis('off')
ax.text(0,4.22,'a  场景 A：同核跨 Task 仍经过 DDR',fontsize=9)
box(ax,.2,2.85,2.25,.85,'Task 1\n生产操作');box(ax,4,2.85,1.6,.85,'DDR',fc='.92');box(ax,7.25,2.85,2.25,.85,'Task 2\n消费操作')
arrow(ax,(2.45,3.27),(4,3.27));arrow(ax,(5.6,3.27),(7.25,3.27))
ax.text(3.2,3.56,'COPY_OUT',ha='center',fontsize=7.8);ax.text(6.4,3.56,'COPY_IN',ha='center',fontsize=7.8)
ax.text(0,2.12,'b  场景 B：同核子图合并，保留可驻留数据',fontsize=9)
ax.add_patch(Rectangle((.15,.55),9.4,1.2,fill=False,ls='--',lw=.7))
box(ax,.35,.78,2.25,.65,'生产操作');box(ax,4.0,.78,1.75,.65,'L1 / UB',fc='.92');box(ax,7.0,.78,2.25,.65,'消费操作')
arrow(ax,(2.60,1.10),(4,1.10));arrow(ax,(5.75,1.10),(7,1.10))
ax.text(4.85,.16,'同一核心的一个 Task；容量不足仍可能发生换出',ha='center',fontsize=8)
save(fig,'图7-1_Task边界与数据复用')

fig,axs=plt.subplots(1,2,figsize=(7,2.8),layout='constrained')
for key,label_,line,mark in [('A','问题一','-','o'),('B','问题二','--','s')]:
    vals=[stat[key][str(i)]['mean'] for i in range(2,6)]
    axs[0].plot(n,[1]+vals,marker=mark,ls=line,color='.15' if key=='A' else '.5',ms=4,lw=1.2,label=label_)
axs[0].set(xlabel='核心数',ylabel='平均加速比',xticks=n);axs[0].legend(frameon=False,fontsize=8)
x=np.arange(4)
for key,off,fc,ha in [('A',-.18,'.25',None),('B',.18,'white','///')]:
    axs[1].bar(x+off,[stat[key][str(i)]['added_mib'] for i in range(2,6)],width=.35,color=fc,edgecolor='.2',lw=.6,hatch=ha,label='问题一' if key=='A' else '问题二')
axs[1].set(xticks=x,xticklabels=[2,3,4,5],xlabel='核心数',ylabel='平均额外搬运 / MiB');axs[1].legend(frameon=False,fontsize=8)
for a,l,t in zip(axs,'ab',['系统完工时间对应的加速比','官方额外搬运']):tidy(a);label(a,l,t)
save(fig,'图7-2_问题二求解结果')

rr5=[r for r in ab if r['cores']=='5'];pair2=[]
for r in rr5:
    pair2.append({'case':r['case'],'saved_added_mib':(float(r['A_added_copy_bytes'])-float(r['B_added_copy_bytes']))/MIB,'time_reduction_percent':100*(1-float(r['B_makespan_cycles'])/float(r['A_makespan_cycles']))})
write('问题二五核配对变化.csv',pair2)
fig,axs=plt.subplots(1,2,figsize=(7,3.1),layout='constrained',gridspec_kw={'width_ratios':[1.4,1]})
xs=[r['saved_added_mib'] for r in pair2];ys=[r['time_reduction_percent'] for r in pair2]
axs[0].scatter(xs,ys,s=24,facecolors='white',edgecolors='.2',lw=.7)
axs[0].axhline(0,color='.5',lw=.7);axs[0].axvline(0,color='.5',lw=.7)
axs[0].set(xlabel='额外搬运减少量 / MiB',ylabel='耗时缩短率 / %')
tot=np.array([stat[s]['5']['added_mib'] for s in ['A','B']]);spill=np.array([stat[s]['5']['spill_mib'] for s in ['A','B']])
axs[1].bar([0,1],spill,color='.3',width=.5,label='缓存换出相关')
axs[1].bar([0,1],tot-spill,bottom=spill,color='white',hatch='///',edgecolor='.3',lw=.6,width=.5,label='其余新增搬运')
axs[1].set(xticks=[0,1],xticklabels=['问题一','问题二'],ylabel='平均额外搬运 / MiB',ylim=(0,19))
axs[1].legend(frameon=False,fontsize=7.3,loc='upper right')
for a,l,t in zip(axs,'ab',['逐图时间与搬运配对','平均搬运构成']):tidy(a);label(a,l,t)
save(fig,'图7-3_通信减少与耗时变化')
stats['q2_added_reduction_pct']=100*(1-tot[1]/tot[0])
stats['q2_less_copy_but_slower']=sum(x>0 and y<0 for x,y in zip(xs,ys))
stats['original_inputs_hashed']=100;stats['frozen_source_files_unchanged']=16
(R/'data/本轮重算核对.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(stats,ensure_ascii=False))
