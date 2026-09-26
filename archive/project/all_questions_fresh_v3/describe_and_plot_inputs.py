#!/usr/bin/env python3
"""Graph-only descriptive analysis of the 100 official input DAGs.

Rebuildable from raw case JSON. It does not load evaluator scores or training labels.
"""
import argparse
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from solver import Graph, read_hardware

FIELDS = ["compute_ops", "weak_components", "largest_component_fraction", "vector_share",
          "compute_cycles", "critical_path_cycles", "shared_input_tensors", "dag_edges",
          "graph_depth_ops", "tensor_count", "total_tensor_bytes", "input_tensor_count",
          "input_tensor_bytes", "output_tensor_count", "output_tensor_bytes", "matrix_cycles",
          "vector_cycles", "work_span_parallelism"]
plt.rcParams.update({"font.family":"sans-serif",
    "font.sans-serif":["Noto Sans CJK SC","WenQuanYi Micro Hei","DejaVu Sans"],
    "font.size":9, "axes.spines.top":False, "axes.spines.right":False,
    "figure.dpi":150, "savefig.dpi":300})
BLUE, ORANGE, GREEN, GRAY, PURPLE = "#0072B2", "#D55E00", "#009E73", "#777777", "#CC79A7"


def quantile(xs, p):
    xs=sorted(float(x) for x in xs)
    pos=(len(xs)-1)*p; i=int(pos); f=pos-i
    return xs[i]*(1-f)+xs[min(i+1,len(xs)-1)]*f


def rankdata(values):
    x=np.asarray(values,float); order=np.argsort(x,kind="mergesort"); ranks=np.empty(len(x))
    i=0
    while i<len(x):
        j=i+1
        while j<len(x) and x[order[j]]==x[order[i]]: j+=1
        ranks[order[i:j]]=(i+1+j)/2; i=j
    return ranks


def profile_graph(raw):
    g=Graph(raw); base=g.profile()
    pipe={"PIPE_M":0,"PIPE_V":0}
    for op in g.ops.values():
        if op.get("pipe") in pipe: pipe[op["pipe"]]+=int(op.get("cycles",0))
    depth={}
    for v in g.order: depth[v]=1+max((depth[p] for p in g.pred[v]),default=0)
    ext=sorted(g.inputs); outputs=sorted(g.outputs)
    base.update({
        "dag_edges":sum(len(g.succ[v]) for v in g.ops),
        "graph_depth_ops":max(depth.values(),default=0),
        "tensor_count":len(g.tensors),
        "total_tensor_bytes":sum(int(t.get("size",0)) for t in g.tensors.values()),
        "input_tensor_count":len(ext),
        "input_tensor_bytes":sum(int(g.tensors[t].get("size",0)) for t in ext),
        "output_tensor_count":len(outputs),
        "output_tensor_bytes":sum(int(g.tensors[t].get("size",0)) for t in outputs),
        "matrix_cycles":pipe["PIPE_M"],"vector_cycles":pipe["PIPE_V"],
        "work_span_parallelism":base["compute_cycles"]/max(1,base["critical_path_cycles"])})
    return g,base


def load_rows(data_dir):
    expected={r["case"]:r for r in csv.DictReader((HERE/"input_profiles.csv").open(encoding="utf-8"))}
    rows=[]; graphs={}
    for case in sorted(expected):
        raw_bytes=(data_dir/(case+".json")).read_bytes()
        raw=json.loads(raw_bytes); g,r=profile_graph(raw)
        sha=hashlib.sha256(raw_bytes).hexdigest()
        if sha!=expected[case]["sha256"]: raise ValueError("input hash mismatch: "+case)
        for k in ("compute_ops","weak_components","largest_component_fraction",
                  "vector_share","compute_cycles","critical_path_cycles","shared_input_tensors"):
            if abs(float(r[k])-float(expected[case][k]))>1e-10:
                raise ValueError("profile mismatch: %s %s"%(case,k))
        r.update(case=case,sha256=sha); rows.append(r); graphs[case]=g
    if len(rows)!=100: raise ValueError("expected 100 graphs")
    return rows,graphs


def summarize(rows):
    ans={"n_cases":len(rows),"fields":{}}
    for k in FIELDS:
        vals=[float(r[k]) for r in rows]
        ans["fields"][k]={"n":len(vals),"min":min(vals),"q1":quantile(vals,.25),
          "median":quantile(vals,.5),"mean":statistics.mean(vals),"q3":quantile(vals,.75),"max":max(vals)}
    ans["counts"]={
      "single_component":sum(int(r["weak_components"])==1 for r in rows),
      "multiple_components":sum(int(r["weak_components"])>1 for r in rows),
      "at_least_five_components":sum(int(r["weak_components"])>=5 for r in rows),
      "shared_input_nonzero":sum(int(r["shared_input_tensors"])>0 for r in rows),
      "vector_share_over_half":sum(float(r["vector_share"])>.5 for r in rows),
      "sha_and_profile_verified":len(rows)}
    return ans


def savefig(fig,out):
    out.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(out.with_suffix(".png"),dpi=300,bbox_inches="tight")
    fig.savefig(out.with_suffix(".pdf"),bbox_inches="tight")
    plt.close(fig)


def fig1(rows,out):
    fig,axs=plt.subplots(2,2,figsize=(9.2,6.2),constrained_layout=True)
    specs=[("compute_ops",True,"Compute operators"),("weak_components",True,"Weak components"),
           ("largest_component_fraction",False,"Largest component / graph"),
           ("vector_share",False,"Vector-pipeline cycle share")]
    for ax,(key,log,title) in zip(axs.flat,specs):
        x=np.array([r[key] for r in rows],float)
        if log: x=np.log10(1+x); xlabel="log10(1 + count)"
        else: xlabel="Fraction"
        ax.hist(x,bins="fd",color=BLUE,alpha=.84,edgecolor="white")
        ax.set(title=title,xlabel=xlabel,ylabel="Cases"); ax.grid(axis="y",alpha=.18)
    fig.suptitle("100 official input graphs · structural distributions",fontsize=12)
    savefig(fig,out/"fig01_input_distributions")


def fig2(rows,out):
    w=np.log10([r["compute_cycles"] for r in rows])
    s=np.log10([r["critical_path_cycles"] for r in rows])
    fig=plt.figure(figsize=(7.2,5.8),constrained_layout=True)
    gs=fig.add_gridspec(2,2,width_ratios=(4,1),height_ratios=(1,4))
    top=fig.add_subplot(gs[0,0]); main=fig.add_subplot(gs[1,0],sharex=top)
    side=fig.add_subplot(gs[1,1],sharey=main)
    top.hist(w,bins="fd",color=BLUE,alpha=.8)
    main.scatter(w,s,c=GREEN,s=26,alpha=.78,edgecolors="white",linewidths=.3)
    lo=min(w.min(),s.min()); hi=max(w.max(),s.max())
    main.plot([lo,hi],[lo,hi],"--",color=GRAY,lw=1,label="work = span")
    main.set(xlabel="log10(total compute cycles)",ylabel="log10(critical-path cycles)")
    main.legend(frameon=False); side.hist(s,bins="fd",orientation="horizontal",color=ORANGE,alpha=.8)
    top.tick_params(labelbottom=False); side.tick_params(labelleft=False); side.set_xlabel("Cases")
    fig.suptitle("Work/span reveals graph-level parallelism limits",fontsize=12)
    savefig(fig,out/"fig02_work_span_joint")


def fig3(rows,out):
    c=np.array([r["weak_components"] for r in rows],float)
    f=np.array([r["largest_component_fraction"] for r in rows],float)
    p=np.array([r["work_span_parallelism"] for r in rows],float)
    fig,ax=plt.subplots(figsize=(7.2,4.8),constrained_layout=True)
    im=ax.scatter(np.log10(1+c),f,c=np.log10(1+p),cmap="viridis",s=42,alpha=.86,
                  edgecolors="white",linewidths=.3)
    ax.axvline(np.log10(6),color=ORANGE,ls="--",lw=1.2,
               label="5 components: opportunity, not a balance guarantee")
    ax.set(xlabel="log10(1 + weak-component count)",
           ylabel="Largest component / all compute nodes",ylim=(-.03,1.03))
    fig.colorbar(im,ax=ax,label="log10(1 + work/span)")
    ax.legend(frameon=False); ax.set_title("Decomposability differs strongly by case")
    savefig(fig,out/"fig03_component_structure")


def fig4(rows,out):
    v=np.array([r["vector_share"] for r in rows],float)
    shared=np.array([r["shared_input_tensors"] for r in rows],float)
    ops=np.array([r["compute_ops"] for r in rows],float)
    cyc=np.array([r["compute_cycles"] for r in rows],float)
    fig,axs=plt.subplots(1,2,figsize=(9.5,4.4),constrained_layout=True)
    sc=axs[0].scatter(v,np.log10(1+shared),c=np.log10(cyc),cmap="plasma",s=38,
                      alpha=.84,edgecolors="white",linewidths=.3)
    axs[0].set(xlabel="Vector share of compute cycles",
               ylabel="log10(1 + shared external-input tensors)")
    fig.colorbar(sc,ax=axs[0],label="log10(total compute cycles)")
    axs[0].set_title("(a) Pipe mix and shared-input opportunity")
    axs[1].scatter(np.log10(1+ops),np.log10(1+shared),c=BLUE,s=28,alpha=.72,
                   edgecolors="white",linewidths=.25)
    axs[1].set(xlabel="log10(1 + compute operators)",
               ylabel="log10(1 + shared external-input tensors)")
    axs[1].set_title("(b) Graph size and shared inputs")
    for a in axs: a.grid(alpha=.18)
    savefig(fig,out/"fig04_pipe_and_shared_inputs")


def fig5(rows,out):
    keys=["compute_ops","weak_components","largest_component_fraction","vector_share",
          "compute_cycles","critical_path_cycles","work_span_parallelism","shared_input_tensors"]
    labels=["Ops","WCC","Largest\nfraction","Vector\nshare","Work","Span","Work/span","Shared\ninputs"]
    x=np.column_stack([rankdata([r[k] for r in rows]) for k in keys])
    corr=np.corrcoef(x,rowvar=False)
    fig,ax=plt.subplots(figsize=(8.2,7),constrained_layout=True)
    im=ax.imshow(corr,vmin=-1,vmax=1,cmap="coolwarm")
    ax.set(xticks=range(len(labels)),yticks=range(len(labels)),xticklabels=labels,yticklabels=labels)
    ax.tick_params(axis="x",labelrotation=35)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j,i,"%.2f"%corr[i,j],ha="center",va="center",fontsize=7,
                    color="white" if abs(corr[i,j])>.65 else "black")
    fig.colorbar(im,ax=ax,label="Spearman rank correlation")
    ax.set_title("Rank correlations of graph-only descriptors")
    savefig(fig,out/"fig05_spearman_heatmap")


def fig6(rows,out):
    groups=[[r for r in rows if int(r["weak_components"])==1],
            [r for r in rows if int(r["weak_components"])>1]]
    labels=["One component (n=%d)"%len(groups[0]),"Multiple components (n=%d)"%len(groups[1])]
    rng=np.random.default_rng(17)
    fig,axs=plt.subplots(1,2,figsize=(9.2,4.4),constrained_layout=True)
    for ax,key,title in zip(axs,("largest_component_fraction","work_span_parallelism"),
                            ("Largest-component fraction","log10(work/span)")):
        for i,g in enumerate(groups):
            vals=np.array([r[key] for r in g],float)
            shown=np.log10(vals) if key=="work_span_parallelism" else vals
            ax.scatter(i+rng.uniform(-.08,.08,len(vals)),shown,s=18,alpha=.46,
                       color=(ORANGE,BLUE)[i],edgecolors="none")
            q1,med,q3=np.quantile(shown,[.25,.5,.75])
            ax.plot([i-.18,i+.18],[med,med],color="black",lw=2.2)
            ax.vlines(i,q1,q3,color="black",lw=3)
        ax.set(xticks=[0,1],xticklabels=labels,ylabel=title,title=title)
        ax.grid(axis="y",alpha=.2)
    fig.suptitle("Structural regimes · descriptive, not causal",fontsize=12)
    savefig(fig,out/"fig06_component_regimes")


def dominates(a,b):
    return np.all(a<=b+1e-12) and np.any(a<b-1e-12)


def fig7(rows,graphs,config,out,proxy_path):
    cfg=read_hardware(config)
    med=quantile([r["compute_ops"] for r in rows],.5)
    case=min(rows,key=lambda r:(abs(r["compute_ops"]-med),r["case"]))["case"]
    g=graphs[case]; fig,axs=plt.subplots(1,3,figsize=(12.2,4.4),constrained_layout=True)
    output=[]
    for q,ax in zip((1,2,3),axs):
        # Compare four fixed structural baselines directly. Avoid learned weights
        # and evaluator labels; this plot is a graph-only illustration of trade-offs.
        cs=[]
        for mode in ("component_scalar","component_vector","component_affinity","join_tail"):
            plan=g.build(5,mode,cfg)
            features,detail=g.features(plan,cfg,q)
            cs.append({"name":mode,"features":features,"detail":detail})
        xy=np.array([[float(c["features"][0]),float(c["features"][2])] for c in cs])
        front=np.array([not any(dominates(xy[j],xy[i]) for j in range(len(cs)) if j!=i)
                        for i in range(len(cs))])
        ax.scatter(xy[~front,0],xy[~front,1],s=30,c=GRAY,alpha=.55,label="Dominated proxy")
        ax.scatter(xy[front,0],xy[front,1],s=42,c=BLUE,alpha=.9,label="Non-dominated proxy")
        ax.set(xlabel="Resource floor (cycles)",ylabel="Estimated DDR time (cycles)",
               title="Q%d · %d plans"%(q,len(cs)))
        ax.grid(alpha=.18)
        for i,c in enumerate(cs):
            output.append({"case":case,"question":q,"cores":5,"candidate":c["name"],
                "resource_floor_cycles":xy[i,0],"estimated_ddr_cycles":xy[i,1],
                "logical_memory_excess_bytes":c["detail"].get("logical_excess_bytes",0),
                "official_evaluator_used":0})
    axs[0].legend(frameon=False,fontsize=8)
    fig.suptitle("%s · graph-only proxy trade-offs, not official scores"%case)
    proxy_path.parent.mkdir(parents=True,exist_ok=True)
    with proxy_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
    savefig(fig,out/"fig07_graph_only_pareto")
    return case


def fig8(out):
    fig,ax=plt.subplots(figsize=(11,6.6),constrained_layout=True)
    ax.set(xlim=(0,12),ylim=(0,8));ax.axis("off")
    def box(x,y,w,h,text,color,size=9):
        patch=FancyBboxPatch((x,y),w,h,boxstyle="round,pad=.04,rounding_size=.08",
            linewidth=1.2,edgecolor=color,facecolor=color+"18")
        ax.add_patch(patch);ax.text(x+w/2,y+h/2,text,ha="center",va="center",fontsize=size)
    def arrow(x1,y1,x2,y2):
        ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle="-|>",mutation_scale=12,
                                     color=GRAY,linewidth=1))
    box(3.5,6.9,5,0.7,"输入 DAG + 核数 N + 固定硬件参数",BLUE,11)
    box(3.5,5.7,5,0.7,"预处理：依赖、周期、Pipe、张量、弱连通分量",BLUE,9)
    arrow(6,6.9,6,6.4)
    items=[
      (.3,BLUE,"问题一 · 场景 A","1 子图 = 1 Task\n同核边界也经 DDR\n同核等待 100；跨核等待 1000 cycles\n目标：(T, 新增 DDR 字节, spill)"),
      (4.25,ORANGE,"问题二 · 场景 B","同核子图并入单 Task\n跨核 COPY + 500-cycle 同步\n私有 L1/UB：512/128 KiB\n目标：(T, 跨核字节, 内存超额)"),
      (8.2,GREEN,"问题三 · 场景 B + L2","沿用问题二 Task 规则\nFIFO 只读 L2：1 MiB / 250 B·cycle^-1\n共享 DDR：60 B·cycle^-1\n目标：(T, DDR 字节, −L2 命中字节)")]
    for x,color,title,body in items:
        box(x,3.15,3.5,1.95,title+"\n\n"+body,color,8)
        arrow(6,5.7,x+1.75,5.1)
    box(3.2,1.0,5.6,.9,"图结构与固定规则 → 单方案 → 冻结 → 官方评测核验",PURPLE,10)
    for x in (2.05,6,9.95): arrow(x,3.15,6,1.9)
    ax.text(6,.4,"机制示意图；不表示官方评测器的完整离散事件时间线",ha="center",color=GRAY,fontsize=8)
    savefig(fig,out/"fig08_three_scene_model")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-dir",type=Path,required=True)
    ap.add_argument("--config",type=Path,required=True)
    ap.add_argument("--out",type=Path,default=HERE)
    args=ap.parse_args()
    rows,graphs=load_rows(args.data_dir); summary=summarize(rows)
    summary["provenance"]={"input_profiles":"input_profiles.csv",
      "raw_graphs":str(args.data_dir),"hash_profile_checks":"100/100 pass",
      "statistics_use_evaluator_outputs":False,"log_transform":"figures only; source-scale values retained"}
    args.out.mkdir(parents=True,exist_ok=True); figures=args.out/"figures";figures.mkdir(exist_ok=True)
    with (args.out/"input_descriptive_stats.json").open("w",encoding="utf-8") as f:
        json.dump(summary,f,ensure_ascii=False,indent=2)
    with (args.out/"preprocessed_profiles.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["case","sha256"]+FIELDS);w.writeheader()
        for r in rows:w.writerow({k:r[k] for k in ["case","sha256"]+FIELDS})
    fig1(rows,figures);fig2(rows,figures);fig3(rows,figures);fig4(rows,figures)
    fig5(rows,figures);fig6(rows,figures)
    case=fig7(rows,graphs,args.config,figures,args.out/"graph_only_proxy_candidates.csv")
    fig8(figures)
    print(json.dumps({"n_cases":len(rows),"checks":"100/100 input hashes and seven base profiles match",
      "counts":summary["counts"],"median_size_pareto_case":case,"figure_count":8,
      "out":str(args.out)},ensure_ascii=False))
if __name__=="__main__":main()
