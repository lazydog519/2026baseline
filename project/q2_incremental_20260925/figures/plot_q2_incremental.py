import csv,json
from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
ROOT=Path(__file__).parent; DATA=ROOT/'q2_incremental_20260925'; FIG=ROOT/'q2_figures'; FIG.mkdir(exist_ok=True)
agg=json.loads((DATA/'aggregate.json').read_text(encoding='utf-8'))
final=list(csv.DictReader((DATA/'final_per_case_metrics.csv').open(encoding='utf-8')))
cold=list(csv.DictReader((ROOT/'q2_cold'/'final'/'per_case_metrics.csv').open(encoding='utf-8')))
new=list(csv.DictReader((DATA/'candidate_results.csv').open(encoding='utf-8')))
NAVY='#245A78'; ORANGE='#C56A2D'; GREY='#818A91'; TEAL='#2B7A78'; RED='#B64B4B'
mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','Helvetica','DejaVu Sans'],'font.size':9,'axes.labelsize':9,'axes.titlesize':10,'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':8,'axes.spines.right':False,'axes.spines.top':False,'axes.linewidth':0.8,'svg.fonttype':'none','pdf.fonttype':42,'savefig.facecolor':'white'})
def save(fig,name):
 fig.tight_layout()
 fig.savefig(FIG/f'{name}.svg',bbox_inches='tight')
 fig.savefig(FIG/f'{name}.pdf',bbox_inches='tight')
 fig.savefig(FIG/f'{name}.png',dpi=300,bbox_inches='tight')
 fig.savefig(FIG/f'{name}.tiff',dpi=600,bbox_inches='tight')
 plt.close(fig)
# Figure 1: refined selection changes mean-case acceleration.
cores=np.array([2,3,4,5]); before=np.array([sum(float(r['speedup']) for r in cold if int(r['cores'])==n)/100 for n in cores]); after=np.array([agg['arithmetic_mean_speedup'][str(n)] for n in cores]);
fig,ax=plt.subplots(figsize=(6.6,4.2)); x=np.arange(4); width=.34
ax.bar(x-width/2,before,width,color=GREY,label='Cold-start incumbent');ax.bar(x+width/2,after,width,color=NAVY,label='Incremental selection')
for i,n in enumerate(cores): ax.text(i+width/2,after[i]+.11,f"+{(after[i]/before[i]-1)*100:.2f}%",ha="center",va="bottom",fontsize=7)
ax.set_xticks(x,cores);ax.set_xlabel('Core count');ax.set_ylabel('Mean speedup (×)');ax.set_title('Q2 incremental refinement: cold start (gray) vs retained search (blue)');ax.grid(axis="y",color="#D9DEE2",lw=.7);ax.set_axisbelow(True);save(fig,"q2_incremental_mean_speedup")
# Figure 2: case-level percentage makespan changes on 5 cores.
fc={(r['case'],int(r['cores'])):r for r in final};bc={(r['case'],int(r['cores'])):r for r in cold};vals=[]
for i in range(1,101):
 c=f'case_{i:03d}'; b=float(bc[c,5]['makespan_cycles']);f=float(fc[c,5]['makespan_cycles']);vals.append((c,(b-f)/b*100))
vals.sort(key=lambda z:z[1],reverse=True); names=[x[0].replace('case_','') for x in vals]; y=np.array([x[1] for x in vals]);colors=[TEAL if v>1e-9 else (RED if v< -1e-9 else GREY) for v in y]
fig,ax=plt.subplots(figsize=(8,4.3));ax.bar(np.arange(100),y,color=colors,width=.9);ax.axhline(0,color='#263238',lw=.8);ax.set_xticks([0,19,39,59,79,99],['Best','20','40','60','80','Worst']);ax.set_xlabel('100 cases ranked by makespan reduction');ax.set_ylabel('Change vs cold-start (%)');ax.set_title('Per-case effect of retaining first-range wins and testing neighbors (5 cores)');ax.grid(axis='y',color='#D9DEE2',lw=.7);ax.set_axisbelow(True);ax.text(.99,.97,f"Improved: {sum(v>0 for v in y)}/100",transform=ax.transAxes,ha='right',va='top',fontsize=8);save(fig,'q2_incremental_case_effect')
# Figure 3: width neighbors measured relative to cached seed makespan.
pts=[r for r in new if r['status']=='ok'];delta=np.array([(int(r['seed_makespan'])-int(r['makespan_cycles']))/int(r['seed_makespan'])*100 for r in pts]);widths=np.array([int(r['band_width']) for r in pts]);cs=np.array([int(r['cores']) for r in pts]); cmap={2:GREY,3:TEAL,4:ORANGE,5:NAVY}
fig,ax=plt.subplots(figsize=(6.6,4.2));
for n in [2,3,4,5]:
 ix=cs==n;ax.scatter(widths[ix],delta[ix],s=24,alpha=.82,color=cmap[n],label=f'{n} cores',edgecolors='white',linewidths=.35)
ax.axhline(0,color='#263238',lw=.8);ax.set_xlabel('Neighbor band width');ax.set_ylabel('Makespan improvement vs cached seed (%)');ax.set_title('Official evaluation of 40 neighboring-width candidates');ax.grid(color='#D9DEE2',lw=.7);ax.set_axisbelow(True);fig.text(.5,.015,"2 cores: gray     3 cores: teal     4 cores: orange     5 cores: navy",ha="center",fontsize=8);save(fig,"q2_incremental_neighbor_search")
(FIG/'figure_source_data.json').write_text(json.dumps({'aggregate':agg,'n_final_jobs':len(final),'n_cold_jobs':len(cold),'n_neighbor_candidates':len(pts)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'figures':sorted(p.name for p in FIG.iterdir()),'five_core_best_change_pct':float(max(y)),'five_core_worst_change_pct':float(min(y)),'five_core_median_change_pct':float(np.median(y)),'neighbors_better_than_seed':int((delta>0).sum()),'neighbors_equal':int((delta==0).sum()),'neighbors_worse':int((delta<0).sum())},ensure_ascii=False))
