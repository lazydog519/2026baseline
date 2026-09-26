"""Two evidence figures only, generated after the full official recheck.

Adapted from figure-presets F01 (subplot_mosaic) and F05 (paired differences).
Source: mathodology-figure-presets/templates/matplotlib_templates.py.
"""
import argparse
import csv
import gzip
import json
import statistics
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

BLUE, ORANGE, GREEN, GRAY = "#0072B2", "#D55E00", "#009E73", "#7A7A7A"


def save_figure(fig, stem):
    # Adapted from the skill's export helper: one raster and one vector master.
    fig.savefig(stem.with_suffix(".png"), dpi=240, bbox_inches="tight")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def load_gzip(path):
    with gzip.open(path,"rt",encoding="utf-8") as stream:
        return json.load(stream)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path,required=True)
    args=parser.parse_args()
    p=args.project.resolve()
    out=p/"q2_cold"/"final"
    summary=json.loads((out/"aggregate.json").read_text(encoding="utf-8"))
    assert summary["official_recheck"] and summary["complete_cases"]==100
    rows=list(csv.DictReader((out/"per_case_metrics.csv").open(encoding="utf-8")))
    grouped={n:[r for r in rows if int(r["cores"])==n] for n in range(2,6)}
    plt.rcParams.update({"font.family":"sans-serif","font.sans-serif":["Microsoft YaHei","SimHei","DejaVu Sans"],
                         "font.size":10,"axes.titlesize":11,"axes.labelsize":10,"axes.unicode_minus":False,
                         "axes.spines.top":False,"axes.spines.right":False,"pdf.fonttype":42})
    fig,axs=plt.subplots(1,3,figsize=(13,4.1),layout="constrained",gridspec_kw={"width_ratios":[1,1.35,1]})
    xs=list(range(1,6))
    a=axs[0]
    a.plot(xs,[summary["baseline_mean_speedup"][str(n)] for n in xs],"o--",c=GRAY,label="分量基线",lw=1.5)
    ys=[summary["arithmetic_mean_speedup"][str(n)] for n in xs]
    a.plot(xs,ys,"o-",c=BLUE,label="独立求解",lw=2)
    for x,y in zip(xs[1:],ys[1:]):
        a.annotate(f"{y:.3f}",(x,y),xytext=(0,8),textcoords="offset points",ha="center",fontsize=9,color=BLUE)
    a.set(title="a  官方平均加速比",xlabel="可用核心数",ylabel="逐例加速比的算术平均",xticks=xs,ylim=(.8,max(ys)+.5))
    a.grid(axis="y",alpha=.18)
    a.legend(frameon=False,loc="upper left")
    a=axs[1]
    improvements=[float(r["reduction_percent"]) for r in grouped[5]]
    a.vlines(range(1,101),0,improvements,color=BLUE,alpha=.5,lw=1)
    a.scatter(range(1,101),improvements,c=BLUE,s=11,zorder=3)
    a.axhline(0,c=GRAY,lw=.8)
    a.set(title=f"b  5 核：{summary['improved_cases']['5']}/100 例改善",xlabel="官方用例编号",ylabel="相对初解的周期减少（%）",xlim=(0,101))
    a.grid(axis="y",alpha=.18)
    a=axs[2]
    values=[[float(r["wall_seconds"]) for r in grouped[n]] for n in range(2,6)]
    boxes=a.boxplot(values,positions=range(2,6),widths=.45,patch_artist=True,showfliers=True,
                    flierprops=dict(marker=".",markersize=3,markerfacecolor=GRAY,markeredgecolor=GRAY),
                    medianprops=dict(color=ORANGE,lw=1.5))
    for patch in boxes["boxes"]:patch.set(facecolor="#CBE4F1",edgecolor=BLUE)
    a.set(title=f"c  独立进程实际耗时\n软时限结束：{summary['time_capped_jobs']}/400 组",xlabel="可用核心数",ylabel="求解耗时（秒，对数轴）",yscale="log",xticks=range(2,6))
    a.grid(axis="y",alpha=.18)
    fig.suptitle("问题二｜100 个用例 × 4 种核数，统一搜索预算",fontsize=13,fontweight="bold")
    save_figure(fig,out/"01_full_results")

    # Case 044 is a declared development example of repeated input traffic;
    # it is not selected post hoc as a typical case or a generalisation result.
    case="case_044"
    baseline_result=None
    for folder in sorted(p.glob("baseline_results*")):
        path=folder/case/"q2_n5"/"result.json.gz"
        if path.is_file():
            baseline_result=load_gzip(path)
            break
    assert baseline_result is not None
    selected=load_gzip(p/"q2_cold"/"full"/case/"n5"/"official_result.json.gz")
    example_row=next(r for r in grouped[5] if r["case"]==case)
    assert baseline_result["makespan"] == int(example_row["baseline_cycles"])
    assert selected["makespan"] == int(example_row["makespan_cycles"])
    fig=plt.figure(figsize=(12,9.2),layout="constrained")
    axes=fig.subplot_mosaic([["convergence","traffic"],["before","after"]],gridspec_kw={"height_ratios":[1,1.85]})
    steps=range(1,25)
    trajectories=[]
    for r in grouped[5]:
        events=[json.loads(s) for s in (p/"q2_cold"/"full"/r["case"] /"n5"/"search.jsonl").read_text(encoding="utf-8").splitlines()]
        best=[e["best_cycles"] for e in events if e["best_cycles"] is not None]
        assert best
        trajectories.append([float(r["singlecore_cycles"])/best[min(j,len(best)-1)] for j in range(24)])
    trajectories=np.asarray(trajectories)
    ax=axes["convergence"]
    for vals in trajectories:ax.plot(steps,vals,c=GRAY,alpha=.08,lw=.7)
    means=trajectories.mean(axis=0)
    ax.plot(steps,means,c=BLUE,lw=2.4,label="100 例均值")
    ax.scatter([1,5,10,20,24],means[[0,4,9,19,23]],c=BLUE,s=22,zorder=5)
    ax.set(title="a  5 核：搜索预算的边际收益",xlabel="累计官方评估次数",ylabel="加速比",xticks=[1,5,10,15,20,24],xlim=(1,24))
    ax.grid(axis="y",alpha=.18)
    ax.legend(frameon=False)
    ax=axes["traffic"]
    labels=["原始搬运","切分增加","缓存换出/换入"]
    fields=["original_graph_copy_bytes","partition_added_copy_bytes","spill_added_copy_bytes"]
    totals=np.zeros(2)
    colors=[GRAY,ORANGE,GREEN]
    for field,label,color in zip(fields,labels,colors):
        data=np.array([r["data_movement_bytes"][field] for r in [baseline_result,selected]])/2**20
        ax.bar([0,1],data,bottom=totals,color=color,label=label,width=.5)
        totals+=data
    for i,t in enumerate(totals):ax.text(i,t+.06,f"{t:.2f}",ha="center",fontsize=10)
    ax.set(title="b  case_044：总 DDR 搬运分解",xticks=[0,1],xticklabels=["初解","独立搜索结果"],ylabel="MiB（1 MiB = $2^{20}$ bytes）",ylim=(0,max(totals)*1.27))
    ax.legend(frameon=False,ncols=1,fontsize=8,loc="upper right")
    pipes=["PIPE_M","PIPE_V","PIPE_MTE2","PIPE_MTE3"]
    colors=[BLUE,GREEN,ORANGE,"#E7A269"]
    xmax=max(baseline_result["makespan"],selected["makespan"])/1000
    for tag,result,title in [("before",baseline_result,"c  case_044：初解"),("after",selected,"d  case_044：独立搜索结果")]:
        ax=axes[tag]
        for core in result["per_core_timeline"]:
            c=core["core_id"]
            for j,pipe in enumerate(pipes):
                spans=[(o["start"]/1000,(o["end"]-o["start"])/1000) for o in core["ops"] if o["pipe"]==pipe and o["end"]>o["start"]]
                ax.broken_barh(spans,(c*5+j-.35,.7),facecolors=colors[j],edgecolors="none")
            ax.axhline(c*5+3.9,color=GRAY,lw=.4,alpha=.4)
        labels=[f"核{c}  {pipe.removeprefix('PIPE_')}" for c in range(5) for pipe in pipes]
        ax.set(yticks=[c*5+j for c in range(5) for j in range(4)],yticklabels=labels,
               xlabel="仿真时间（千周期）",title=f"{title}  ·  T={result['makespan']:,}",xlim=(0,xmax*1.025))
        ax.tick_params(axis="y",labelsize=7.5,length=0)
        ax.invert_yaxis()
        ax.axvline(result["makespan"]/1000,color=GRAY,ls="--",lw=1)
        ax.grid(axis="x",alpha=.15)
    fig.suptitle("搜索如何改善方案｜收敛记录与 DDR 受限用例",fontsize=13,fontweight="bold")
    save_figure(fig,out/"02_search_and_mechanism")
    np.savetxt(out/"convergence_5core.csv",np.c_[list(steps),means],delimiter=",",header="evaluation_count,mean_speedup",comments="")
    (out/"图注与数据说明.md").write_text(
        "# 两张图的口径\n\n"
        "图 1：100×4 组独立求解。a 为固定单核基准除以官方多核 Makespan 后逐例算术平均，1 核定义为 1；"
        "b 为 5 核各例 (初解周期-最终周期)/初解周期，按原用例编号排列；c 为完整独立进程耗时，"
        "箱体表示样本四分位范围、中线为中位数、须线使用 Matplotlib 的 1.5 IQR 规则，离群点保留；不是置信区间。"
        "两进程并发，时间受本机负载影响。\n\n"
        "图 2：a 的灰线为 100 个用例的真实最好已验证加速比，蓝线为均值；提前停止的用例沿用其最终合法解，"
        "没有虚构额外评估。b-d 固定采用开发中已观察的 case_044，解释重复输入搬运与实际使用核心数的关系，"
        "不代表所有用例。b 来自官方搬运分解；c-d 是官方每条 Pipe 的真实操作区间，左右共享时间尺度；"
        "空白核心确实未执行操作，MTE2/3 表示管道占用而非独占 DDR 带宽。峰值检查见逐例 CSV。\n\n"
        "数据：per_case_metrics.csv、full/*/n5/search.jsonl、官方 official_result.json.gz；"
        "绘图入口：solution/q2_cold_figures.py。\n",encoding="utf-8")
    table=["| 核数 | 分量基线均值 | 独立求解均值 | 改善用例数 | 求解耗时中位数（秒） |",
           "|---:|---:|---:|---:|---:|", "| 1 | 1.000000 | 1.000000 | 单核定义 | — |"]
    for n in range(2,6):
        key=str(n)
        table.append(f"| {n} | {summary['baseline_mean_speedup'][key]:.6f} | "
                     f"{summary['arithmetic_mean_speedup'][key]:.6f} | {summary['improved_cases'][key]}/100 | "
                     f"{summary['median_wall_seconds'][key]:.2f} |")
    gain=100*(summary["arithmetic_mean_speedup"]["5"]/summary["baseline_mean_speedup"]["5"]-1)
    section=("\n".join(table)+"\n\n"
        f"5 核平均加速比相对分量基线提高 {gain:.2f}%。"
        +("尚未达到先前希望的 6；该数字仅作为目标，不作为结果约束。" if summary['arithmetic_mean_speedup']['5']<6 else "")+
        f"全量搜索共调用原版评估器 {summary['total_official_search_evaluations']} 次，"
        f"另有 {summary['total_pruned_candidates']} 个候选因明确下界而省去正式评估。"
        f"搜索中记录 {summary['infeasible_candidates']} 个不可行候选；最终 400 份方案全部合法，并逐份独立重新评估一致。"
        f"原附件 {summary['official_files_unchanged']} 个文件哈希均未改变。\n\n"
        f"{summary['time_capped_jobs']} 组因时间预算停止，最长完整进程耗时 {summary['max_wall_seconds']:.2f} 秒。"
        "较大用例可能来不及完成 24 次评估，不剔除它们、不额外加时。有限搜索也可能造成个别用例 5 核慢于 4 核；"
        "本次没有跨核数读取历史答案修饰该现象。\n\n"
        f"case_044 的初解为 {baseline_result['makespan']} cycles，独立求解后为 {selected['makespan']} cycles。"
        "其图用于解释减少重复 DDR 输入读取的机制，不代表平均效果。\n\n"
        "当前统计为一套冻结规则、统一预算、每例独立启动的实测。旧离线选优在预算和候选来源上不同，不能当作公平的同预算对照。"
        "没有声称未知图泛化、全局最优或单独某模块的因果贡献；这些需要另外设计实验。\n\n"
        "![全量结果](q2_cold/final/01_full_results.png)\n\n"
        "![搜索与机制](q2_cold/final/02_search_and_mechanism.png)\n")
    report=p/"技术思路稿-问题二独立求解.md"
    text=report.read_text(encoding="utf-8")
    start=text.index("## 5. 全量结果")
    end=text.index("## 6. 图表与提交复现")
    report.write_text(text[:start]+"## 5. 全量结果\n\n"+section+"\n"+text[end:],encoding="utf-8")
    print("Generated exactly two figures (each PNG + PDF).")


if __name__=="__main__":
    main()
