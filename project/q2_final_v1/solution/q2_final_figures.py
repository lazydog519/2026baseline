"""Render seven standalone figures from q2_final_v1's measured outputs."""
import argparse,csv,gzip,json,statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
BLUE='#0072B2'; ORANGE='#D55E00'; GREEN='#009E73'; GRAY='#777777'; PALE='#CBE4F1'
def loadgz(p):
  with gzip.open(p,'rt',encoding='utf-8') as f:return json.load(f)
def save(fig,out,name):
  fig.savefig(out/(name+'.png'),dpi=240,bbox_inches='tight')
  fig.savefig(out/(name+'.pdf'),bbox_inches='tight')
  plt.close(fig)
def main():
  ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]);a=ap.parse_args();pkg=a.package.resolve();out=pkg/'figures';out.mkdir(exist_ok=True)
  agg=json.loads((pkg/'results/aggregate.json').read_text(encoding='utf-8'))
  rows=list(csv.DictReader((pkg/'results/per_case_metrics.csv').open(encoding='utf-8-sig')))
  groups={n:[r for r in rows if int(r['cores'])==n] for n in range(2,6)}
  plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'axes.unicode_minus':False})
  # 1: effectiveness relative to the freshly measured Q2 one-core reference.
  fig,ax=plt.subplots(figsize=(7.0,4.4),layout='constrained');xs=list(range(1,6));ys=[1.0]+[agg['mean_speedup'][str(n)] for n in range(2,6)];base=[1.0]+[agg['initial_mean_speedup'][str(n)] for n in range(2,6)]
  ax.plot(xs,base,'o--',color=GRAY,label='Initial Q2 plan');ax.plot(xs,ys,'o-',color=BLUE,lw=2.2,label='CILC search')
  for x,y in zip(xs[1:],ys[1:]):ax.annotate(f'{y:.3f}',(x,y),xytext=(0,8),textcoords='offset points',ha='center',color=BLUE)
  ax.set(xlabel='Available cores',ylabel='Arithmetic mean speedup (T1/Tn)',xticks=xs,title='Q2 performance across 100 official cases');ax.grid(axis='y',alpha=.2);ax.legend(frameon=False);save(fig,out,'q2_fig1_mean_speedup')
  # 2: paired case-level improvement at five cores.
  vals=np.array([float(r['reduction_percent']) for r in groups[5]]);order=np.argsort(vals);fig,ax=plt.subplots(figsize=(9,4.4),layout='constrained');ax.bar(np.arange(1,101),vals[order],color=np.where(vals[order]>=0,BLUE,ORANGE),width=.85);ax.axhline(0,color=GRAY,lw=.8);ax.set(xlabel='Cases sorted by cycle reduction',ylabel='Makespan reduction vs initial plan (%)',title=f'Five-core paired effect: {agg["improved_vs_initial"]["5"]}/100 improved');ax.grid(axis='y',alpha=.18);save(fig,out,'q2_fig2_five_core_reduction')
  # 3: actual solve wall time; show outliers, log scale.
  fig,ax=plt.subplots(figsize=(7,4.4),layout='constrained');data=[[float(r['wall_seconds']) for r in groups[n]] for n in range(2,6)];bp=ax.boxplot(data,positions=range(2,6),patch_artist=True,showfliers=True,flierprops={'marker':'.','markersize':3,'color':GRAY},medianprops={'color':ORANGE,'linewidth':1.5});
  for b in bp['boxes']:b.set(facecolor=PALE,edgecolor=BLUE)
  ax.set(xlabel='Available cores',ylabel='Independent solver process time (s, log scale)',yscale='log',xticks=range(2,6),title='Search cost per case');ax.grid(axis='y',alpha=.2);save(fig,out,'q2_fig3_solve_time')
  # 4: average best-so-far speedup over official evaluator calls.
  trajectories=[]
  for r in groups[5]:
    d=pkg/'results/runs'/r['case']/'n5';events=[json.loads(s) for s in (d/'search.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()];ev=[e for e in events if e.get('event')=='evaluation' and e.get('status')=='ok'];one=float(r['singlecore_cycles']);best=[];current=one/float(r['initial_cycles'])
    for e in ev:
      current=max(current,one/float(e['makespan_cycles']));best.append(current)
    if not best:continue
    trajectories.append([best[min(k,len(best)-1)] for k in range(8)])
  m=np.array(trajectories).mean(axis=0);fig,ax=plt.subplots(figsize=(7,4.4),layout='constrained');ax.plot(np.arange(1,9),m,'o-',color=BLUE,lw=2);ax.set(xlabel='Official candidate evaluations',ylabel='Mean best-so-far speedup',title='Five-core search convergence',xticks=range(1,9));ax.grid(alpha=.2);save(fig,out,'q2_fig4_convergence')
  # 5-7: predeclared diagnostic case_044; exact official evaluator traces.
  ex=pkg/'results/examples';initial=loadgz(ex/'case_044_n5_initial.json.gz');final=loadgz(ex/'case_044_n5_selected.json.gz')
  fig,ax=plt.subplots(figsize=(6.8,4.5),layout='constrained');fields=['original_graph_copy_bytes','partition_added_copy_bytes','spill_added_copy_bytes'];labels=['Original graph copies','Partition-added copies','Spill copies'];colors=[GRAY,ORANGE,GREEN];bot=[0,0]
  for field,label,c in zip(fields,labels,colors):
    v=[initial['data_movement_bytes'][field]/2**20,final['data_movement_bytes'][field]/2**20];ax.bar([0,1],v,bottom=bot,color=c,label=label,width=.52);bot=[bot[i]+v[i] for i in range(2)]
  ax.set(xticks=[0,1],xticklabels=['Initial Q2 plan','Selected CILC plan'],ylabel='Moved data (MiB)',title='Case 044: official traffic decomposition');ax.legend(frameon=False,fontsize=8);ax.grid(axis='y',alpha=.16);save(fig,out,'q2_fig5_case044_traffic')
  pipes=['PIPE_M','PIPE_V','PIPE_MTE2','PIPE_MTE3'];pc=[BLUE,GREEN,ORANGE,'#E7A269']
  for idx,(result,label,name) in enumerate([(initial,'Initial Q2 plan','q2_fig6_case044_initial_timeline'),(final,'Selected CILC plan','q2_fig7_case044_selected_timeline')]):
    fig,ax=plt.subplots(figsize=(10,5.2),layout='constrained');
    for core in result['per_core_timeline']:
      c=core['core_id']
      for j,pipe in enumerate(pipes):
        spans=[(o['start']/1000,(o['end']-o['start'])/1000) for o in core['ops'] if o['pipe']==pipe and o['end']>o['start']]
        if spans:ax.broken_barh(spans,(c*4+j-.37,.74),facecolors=pc[j],edgecolors='none')
    ax.set(yticks=[c*4+j for c in range(result['num_cores']) for j in range(4)],yticklabels=[f'Core {c} · {p.replace("PIPE_","")}' for c in range(result['num_cores']) for p in pipes],xlabel='Simulator time (kcycles)',title=f'Case 044: {label} · makespan {result["makespan"]:,} cycles',xlim=(0,result['makespan']/1000*1.025));ax.invert_yaxis();ax.grid(axis='x',alpha=.16);ax.tick_params(axis='y',labelsize=8,length=0);ax.axvline(result['makespan']/1000,color=GRAY,ls='--',lw=.8);save(fig,out,name)
  print('Rendered 7 standalone PNG/PDF figures into',out)
if __name__=='__main__':main()
