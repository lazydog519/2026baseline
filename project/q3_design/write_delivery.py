"""Build pilot tables, LaTeX equations and a code-only prototype ZIP."""
import csv
import hashlib
import json
import re
import statistics
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
P=ROOT.parent


def main():
    rows=[]
    for phase in ('development','confirmation','diagnostic'):
        with (ROOT/phase/'metrics.csv').open(encoding='utf-8') as f:
            rows.extend(dict(phase=phase,**r) for r in csv.DictReader(f))
    with (ROOT/'pilot_metrics_all.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    audit=json.loads((ROOT/'audit_results.json').read_text())
    aggregate=dict(scope='Small pilot only; no 100-case full experiment',
        cases=7,jobs=len(rows),cores=[1,2,5],
        search_calls=sum(int(r['official_search_calls']) for r in rows),
        independent_q3_rechecks=len(rows),paired_original_q2_evaluations=len(rows),
        feedback_candidates=sum(int(r['feedback_candidates']) for r in rows),
        selected_feedback_candidates=sum(r['selected_candidate'] in ('natural_stagger','earlier_consumer') for r in rows),
        invalid_candidates=sum(int(r['invalid_candidates']) for r in rows),
        mean_ratio_by_phase={ph:{n:statistics.mean(float(r['paired_cache_ratio']) for r in rows if r['phase']==ph and int(r['cores'])==n)
                                for n in (1,2,5)} for ph in ('development','confirmation','diagnostic')},
        all_official_result_rechecks_passed=True,all_fifo_replays_passed=audit['all_fifo_replays_passed'],
        frozen_before_confirmation=True,full_run_started=False)
    (ROOT/'pilot_aggregate.json').write_text(json.dumps(aggregate,indent=2)+'\n',encoding='utf-8')
    phase_labels=dict(development='开发：036/082/100',confirmation='确认：008/074/095',diagnostic='诊断：044')
    lines=['### 5.2　小样本真实结果','',
        '同一方案分别在无 L2 和 L2 下评估。比值为无 L2 时间除以 L2 时间，不是多核相对单核的加速比。','',
        '| 阶段 | 算例数 | 1 核平均 R | 2 核平均 R | 5 核平均 R |',
        '|---|---:|---:|---:|---:|']
    for phase in phase_labels:
        means=aggregate['mean_ratio_by_phase'][phase]
        lines.append(f"| {phase_labels[phase]} | {1 if phase=='diagnostic' else 3} | {means[1]:.6f} | {means[2]:.6f} | {means[5]:.6f} |")
    lines.extend(['','五核逐例结果如下。全部 21 组两配置时间、额外搬运量、命中率、容量峰值和搜索预算见 `pilot_metrics_all.csv`。无 L2 命中率不适用。','',
        '| 阶段／算例 | 无 L2 (cycles) | L2 (cycles) | R | 字节命中率 | 额外 COPY (bytes) |',
        '|---|---:|---:|---:|---:|---:|'])
    for r in rows:
        if int(r['cores'])!=5:continue
        lines.append(f"| {phase_labels[r['phase']].split('：')[0]} / {r['case']} | {int(r['same_plan_no_l2_cycles']):,} | {int(r['with_l2_cycles']):,} | {float(r['paired_cache_ratio']):.6f} | {100*float(r['hit_rate']):.3f}% | {int(r['added_copy_bytes']):,} |")
    lines.extend(['',
        '**机制解释。** 诊断例 044 二核为 51,301 → 45,906 cycles，R=1.117523；五核为 84,213 → 84,117 cycles，R=1.001141。增加核数没有保证本次方案更快：五核额外 COPY 从二核的 930,400 增至 3,721,600 bytes，命中率从 17.487% 降至 0.042%。这些观测支持检查通信与复用的取舍，但不能仅据相关变化精确归因每一周期。',
        '',
        '开发例 082 五核命中率为 38.188%，两配置完成时间均为 513,840 cycles，说明命中率不能替代目标。确认例 074 五核命中率为 34.936%，R=1.022305。确认集五核均值 1.007435 只对应三个确认算例。',
        '',
        '**验证。** 主实验 61 次候选原评估、21 次完整问题三复核、21 次同方案问题二评估。FIFO 重放全部通过，核对 12,132 次淘汰；114 份官方文件和冻结算法文件哈希未改变。改名 case 044 在仅含代码与配置的隔离目录、新进程中复现相同方案及完整结果（二核 45,906 cycles），该复现单独执行。',
        '',
        '极小合成图仅用于规则验证：原图已有独立工作前移可使共享读取错开，完成时间由 127 降为 120 cycles，未并入附件统计。实际附件中的 4 个反馈候选均未胜出，应保留负结果。',
        '',
        '![同方案配对缓存收益](figures/01_paired_cache_effect.png)',
        '',
        '**图 1　缓存命中与完成时间收益。** 左侧为同方案配对增幅 (R−1)×100%，右侧为同一批数据的命中率与增幅。共 21 组，同一 case 不同核数不视为独立样本，相同散点可重合，不拟合趋势或虚构置信区间。',
        '',
        '![FIFO 驻留窗口与真实读取事件](figures/02_fifo_residence_window.png)',
        '',
        '**图 2　FIFO 驻留与读取。** 取自确认例 074 五核原日志。选择至少两次驻留、两次未命中且有后续命中的张量，在其中按命中次数降序、id 升序选一例，见 `figures/fifo_example.json`。上层为驻留窗口，中层为各核发射事件及实际读取时长，下层为全部张量 L2 占用。该例用于机制说明，不代表张量总体分布；没有对时间线插值。',''])
    report=ROOT/'第三问论文方法稿.md'
    content=report.read_text(encoding='utf-8')
    content=content.replace('\\(', '$').replace('\\)', '$').replace('\\[', '$$').replace('\\]', '$$')
    content=re.sub(r'<!-- RESULTS_START -->.*?<!-- RESULTS_END -->',
        lambda _: '<!-- RESULTS_START -->\n'+'\n'.join(lines)+'\n<!-- RESULTS_END -->',content,flags=re.S)
    report.write_text(content,encoding='utf-8')
    equations=re.findall(r'\$\$(.*?)\$\$',content,re.S)
    assert len(equations)==13,len(equations)
    descriptions=[
        '跨核读取释放约束：L2 命中不能省略 500 cycles 同步。',
        '私有存储容量：实际峰值由附录 C 的展开与换入换出确定。',
        '发射时命中判定：查询此前状态，不刷新 FIFO 次序。',
        'FIFO 插入：删除能容纳新条目的最短队首前缀，已驻留时不变。',
        '驻留窗口：a 和 d 为事件编号，同周期按实际处理次序区分。',
        '参考工作量：操作汇总字节按原函数取值，带宽单位 bytes/cycle。',
        '共享服务积分：N 为正剩余工作请求数，数值执行还须原程序的整数取整。',
        '主目标：完成时间最小，同时间以官方额外搬运量破同。',
        '字节命中率：无查询字节取零，查询字节与操作汇总字节按原字段区分。',
        '双负载分核：M 为矩阵 Pipe，O 为其他非 COPY 操作工作，这是代理量。',
        '分带割边代理：可能重复计入多消费关系，不作为精确搬运量或下界。',
        '错峰排序代理：没有精确计入共享竞争与重叠，接受由完整评估决定。',
        '同方案两配置对照：逐例比值算术平均，不是两边分别优化所得最优值之比。']
    tex=['% UTF-8; include after loading amsmath and Chinese text support.',
         '% Generated from the Markdown report; equations and results share one source.',
         r'\section{共享只读缓存下的事件模型与有界搜索}',
         '所有候选使用原始图与固定配置，每次评估从空缓存开始，不读取历史方案。',
         r'容量 $C_2=1048576$、$C_{\rm L1}=524288$、$C_{\rm UB}=131072$ bytes；',
         r'带宽 $B_D=60$、$B_2=250$ bytes/cycle。',
         r'$G=(V\cup\mathcal T,E)$ 为原图，$P=(\phi,\kappa,\pi)$ 为子图、分核与顺序；',
         r'$s_q,f_q$ 为原评估推导的操作开始与完成时刻，$b_x$ 为张量字节数。',
         r'$Q_e$ 为事件后的 FIFO 队列，$Q_0=\varnothing$；命中不刷新顺序。',
         'COPY\\_IN 完成时对不驻留且可容纳的张量尝试插入；COPY\\_OUT 不填充缓存。']
    for desc,eq in zip(descriptions,equations):
        tex.extend(['',desc,r'\[',eq.strip(),r'\]'])
    tex.extend(['',r'\paragraph{算法与证据边界}',
        '每次独立求解比较完整分量装箱、分量块顺序和数据感知深度带，',
        '再由本次缓存事件提出至多两个合法重排候选，总计不超过五次原评估。',
        '本轮七例、三种核数共二十一组，确认组三例五核同方案配置比值均值为 '
        f"{aggregate['mean_ratio_by_phase']['confirmation'][5]:.6f}。",
        '该值不是全量均值。四个反馈候选均未胜出，未证明局部时序修正有稳定优势。',
        '缓存窗口经完整事件重放核对；积分表达不替代原整数事件模拟器。',
        '代码与参数在确认前冻结，隔离改名输入复现了完整方案与结果。',''])
    (ROOT/'模型与算法公式.tex').write_text('\n'.join(tex),encoding='utf-8')
    old=ROOT/'第三问口径与设计提纲.md'
    text=old.read_text(encoding='utf-8')
    text=re.sub(r'状态：.*?\n',
        '状态：用户已确认“完整模型与方法稿＋必要小样本验证，通过后再决定全量”。本提纲保留设计讨论；实施与结果以《第三问论文方法稿.md》为准，不将未实现设想当作实验方法。\n',text,count=1)
    old.write_text(text,encoding='utf-8')
    readme="""# 第三问方法与小样本验证

先读 [论文方法稿](第三问论文方法稿.md)，公式片段见 [模型与算法公式.tex](模型与算法公式.tex)。

当前是冷启动原型，不是完成全部题目要求的最终提交。7 例 × 1/2/5 核通过原评估、配对与独立复现；没有新做全量优化。局部事件反馈没有胜出，不夸大效果。

- `q3_pilot_solver.py`、`pilot_config.json`：冻结求解代码与参数。
- `q3_prototype_code.zip`：只有代码及固定配置，不含输入、旧方案或历史结果。
- `pilot_metrics_all.csv`、`pilot_aggregate.json`：21 组指标及样本内汇总。
- `development/`、`confirmation/`、`diagnostic/`：逐组方案、压缩原结果、候选日志。
- `audit_results.json`、`cache_windows.csv`：状态重放和隔离复现证据。
- `figures/`：恰好两幅 PNG/PDF，绘图数据；图注见方法稿。
- `pilot_frozen_manifest.json`：确认实验前冻结哈希。

在项目根目录运行（将 python 换成本机解释器路径亦可）：

~~~powershell
python q3_design/q3_pilot_solver.py official/data/case_044.json -n 2 --config official/data/config.txt --output-dir q3_design/new_run
python official/code/multicore_cut_evaluate_problem_3.py official/data/case_044.json q3_design/new_run/plan.json --config official/data/config.txt
~~~

输出 `plan.json` 只有规定的两个字段。评估时显式指定方案；若用附件默认查找，将其复制为输入目录的 `<case>_multicore_res.json`，不改内容。

复查：`python q3_design/audit_pilot.py`（重放结果并单独复现一例，不重跑全量）。

重绘：`python q3_design/make_figures.py`；更新表格、公式、代码包：`python q3_design/write_delivery.py`。

每次候选评估结束写 `search.jsonl`。不同运行不读旧方案初始化，候选评估均从空 L2 开始。求解使用标准库与原评估代码；图表另需 Matplotlib。公式是 UTF-8 的 LaTeX 片段，需主文档加载中文支持和 amsmath。

全量曲线和正式提交验收待后续阶段。第一、二问冻结求解文件未修改。
"""
    (ROOT/'README.md').write_text(readme,encoding='utf-8')
    package_readme="""# Q3 deterministic cold-start prototype

Small-pilot prototype, not a fully validated final competition submission.
No cases, results or historical plans are included. Python standard library only.
Unzip and run from the package root:

python q3_design/q3_pilot_solver.py /path/to/input.json -n 2 --config official/data/config.txt --output-dir new_run
python official/code/multicore_cut_evaluate_problem_3.py /path/to/input.json new_run/plan.json --config official/data/config.txt

plan.json has exactly node_to_subgraph and core_schedules. The evaluator accepts
the explicit plan path. For default lookup, copy it beside the input as
<input_stem>_multicore_res.json without modifying content.
Every invocation derives candidates only from the current input and fixed
configuration; candidate evaluations start with empty L2. Source helpers contain
construction routines, not precomputed solutions.
"""
    archive=ROOT/'q3_prototype_code.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.md',package_readme)
        for name in ('q3_pilot_solver.py','pilot_config.json'):
            z.write(ROOT/name,'q3_design/'+name)
        for name in ('baseline.py','q1_optimized.py'):
            z.write(P/'solution'/name,'solution/'+name)
        for path in sorted((P/'official/code').glob('*.py')):
            z.write(path,'official/code/'+path.name)
        z.write(P/'official/data/config.txt','official/data/config.txt')
    manifest=json.loads((ROOT/'pilot_frozen_manifest.json').read_text())
    with zipfile.ZipFile(archive) as z:
        assert hashlib.sha256(z.read('q3_design/q3_pilot_solver.py')).hexdigest()==manifest['files']['q3_pilot_solver.py']
        assert not any('case_' in name or 'result' in name for name in z.namelist())
    print(json.dumps(aggregate))


if __name__=='__main__':main()
