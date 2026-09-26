"""Two data figures and prose tables from frozen acceptance; no solving."""
import csv
import gzip
import json
from pathlib import Path
import statistics
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

HERE = Path(__file__).resolve().parent
COLORS = {1: '#0072B2', 2: '#D55E00', 3: '#009E73'}


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def main():
    summary, rows, manifest = read('summary.json'), read('validation_results.json'), read('manifest.json')
    assert not summary['failed_jobs'] and len(rows) == 180
    cases = sorted(manifest['validation'])
    model = read('model.json')
    diagnostics = []
    for row in rows:
        if row['method'] != 'trained': continue
        generation = read(row['path'] + '/generation.json')
        c = next(c for c in generation['candidates'] if c['name'] == generation['selected'])
        x = c['features']; estimate = max(x[0], sum(a*b for a,b in zip(x, model['weights'][str(row['question'])])))
        d = {k: row[k] for k in ('case', 'question', 'cores', 'makespan', 'selected')}
        d.update(predicted_cycles=estimate, relative_prediction_error=estimate/row['makespan']-1)
        if row['question'] == 3:
            d.update(predicted_cache_hit_bytes=c['detail']['cache_request_proxy']['hit_bytes'], actual_cache_hit_bytes=row['cache_stats']['hit_bytes'])
        diagnostics.append(d)
    ds = {str(q): {'mean_absolute_relative_error': statistics.mean(abs(d['relative_prediction_error']) for d in diagnostics if d['question'] == q),
                  'five_core': [d for d in diagnostics if d['question'] == q and d['cores'] == 5]} for q in (1,2,3)}
    (HERE/'prediction_diagnostics.json').write_text(json.dumps(dict(post_freeze_only=True, used_to_select_or_refit=False, summary=ds, rows=diagnostics), indent=2), encoding='utf-8')
    mismatches = []
    labels = read('training_labels.json')
    for label in labels:
        f = read(label['path'] + '/features.json')
        expected = label['data_movement_bytes']['original_graph_copy_bytes'] + label['data_movement_bytes']['partition_added_copy_bytes']
        if f['detail']['no_hit_copy_bytes'] != expected: mismatches.append(label['path'])
    (HERE/'boundary_audit.json').write_text(json.dumps(dict(training_labels_checked=len(labels), boundary_copy_mismatches=mismatches,
        source='official original + partition_added, excluding spill'), indent=2), encoding='utf-8')
    assert not mismatches
    selected = {(r['question'], r['cores'], r['case'], r['method']): r for r in rows}
    figdir = HERE / 'figures'; figdir.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'Microsoft YaHei', 'font.size': 9,
        'axes.spines.top': False, 'axes.spines.right': False, 'axes.unicode_minus': False,
        'pdf.fonttype': 42, 'savefig.dpi': 300, 'axes.labelsize': 9, 'axes.titlesize': 10})

    def save(fig, stem):
        fig.savefig(figdir / (stem + '.png'), bbox_inches='tight', facecolor='white')
        fig.savefig(figdir / (stem + '.pdf'), bbox_inches='tight', facecolor='white')
        plt.close(fig)

    # Adaptation of skill F05/F01: same-case comparison, descriptive means, no invented intervals.
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.25), layout='constrained')
    plotdata = {'cases': cases, 'scope': 'six held-out graphs only', 'curves': {}, 'paired_reductions_pct': {}}
    for q, ax in zip((1, 2, 3), axes):
        for method, label, color, style in [('component_scalar', '单资源装箱对照', '#8B8B8B', '--'),
                                            ('trained', '结构候选＋校准模型', COLORS[q], '-')]:
            values = []
            for n in range(1, 6):
                x = [selected[q, n, case, method] for case in cases]
                value = statistics.mean(r['same_plan_cache_gain'] if q == 3 else r['raw_speedup_vs_original_singlecore'] for r in x)
                if n == 1 and q < 3: value = 1.0
                values.append(value)
            ax.plot(range(1, 6), values, style, color=color, marker='o' if method == 'trained' else 's', ms=3.6, lw=1.5, label=label)
            plotdata['curves'][f'q{q}_{method}'] = values
        ax.set(xticks=range(1, 6), xlabel='核心数', ylabel='同方案无 L2 / 有 L2 完成时间之比' if q == 3 else '平均加速比（原图单核参考）')
        ax.set_title(['(a) 场景 A：Task 边界', '(b) 场景 B：同核复用', '(c) 场景 B＋只读 Cache'][q-1], loc='left', pad=10)
        ax.grid(axis='y', color='#E7E7E7', lw=.6); ax.set_axisbelow(True)
        if q < 3: ax.set_ylim(bottom=.9)
        else: ax.ticklabel_format(axis='y', style='plain', useOffset=False)
    axes[0].legend(frameon=False, fontsize=8, loc='upper left')
    fig.supxlabel('6 个验证图；逐例比值的算术平均。问题一、二单核点按题意归一为 1。', fontsize=9)
    save(fig, 'fig1_core_scaling')

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 3.65), layout='constrained', gridspec_kw={'width_ratios': [1, 1.1]})
    # Skill F05 paired differences; label all six IDs, including regressions.
    for q in (1, 2, 3):
        values = [100*(1-selected[q, 5, case, 'trained']['makespan']/selected[q, 5, case, 'component_scalar']['makespan']) for case in cases]
        y = np.arange(len(cases)) + (q-2)*.19
        left.scatter(values, y, c=COLORS[q], s=24, marker=['o', 's', '^'][q-1], label=f'问题{q}')
        plotdata['paired_reductions_pct'][str(q)] = values
    left.axvline(0, color='#777777', lw=.8)
    left.set(yticks=range(len(cases)), yticklabels=[x.replace('case_', '') for x in cases],
             xlabel='相对装箱对照的完成时间降幅（%）', ylabel='验证图编号')
    left.set_title('(a) 五核逐图效果：负值表示退步', loc='left', pad=10)
    left.grid(axis='x', color='#E7E7E7', lw=.6); left.set_axisbelow(True)
    left.legend(frameon=False, fontsize=8, ncol=3, loc='lower left', bbox_to_anchor=(.08, .02))
    illustration = 'case_050'  # fixed from input structure before validation labels
    path = HERE / 'validation' / illustration / 'q3_n5/trained/official.json.gz'
    with gzip.open(path, 'rt', encoding='utf-8') as f: actual = json.load(f)
    ins = [e for e in actual['cache_events'] if e['event'] == 'insert']
    t = [0] + [e['time']/1000 for e in ins] + [actual['makespan']/1000]
    v = [0] + [e['used_bytes']/1024 for e in ins] + [actual['cache_used_bytes_final']/1024]
    right.step(t, v, where='post', color=COLORS[3], lw=1.5, label='官方记录的 Cache 驻留量')
    right.axhline(actual['cache_capacity_bytes']/1024, color='#777777', ls='--', lw=.8, label='固定容量 1024 KiB')
    hits = [e['time']/1000 for e in actual['cache_events'] if e['event'] == 'hit']
    right.plot(hits, [-25]*len(hits), '|', color=COLORS[3], ms=6, label='命中时刻')
    right.set(xlabel='官方模拟时间（千周期）', ylabel='Cache 驻留量（KiB）', ylim=(-65, 1100), xlim=(0, actual['makespan']/1000))
    right.set_title(f'(b) {illustration.replace("case_", "case ")}：实际插入与命中事件', loc='left', pad=10)
    right.grid(axis='y', color='#E7E7E7', lw=.6); right.legend(frameon=False, fontsize=8, loc='upper left', bbox_to_anchor=(.02, .88))
    right.yaxis.set_major_locator(MaxNLocator(5))
    stat = actual['cache_stats']
    paired = selected[3, 5, illustration, 'trained']['same_plan_cache_gain']
    fig.supxlabel(f'例图由真实验收轨迹绘制：字节命中率 {stat["hit_rate"]:.2%}，同方案 Cache 加速比 {paired:.4f}；命中量不等于时间收益。', fontsize=9)
    plotdata['cache_trace'] = dict(case=illustration, time_kcycles=t, used_kib=v, hit_times_kcycles=hits,
                                   source=str(path.relative_to(HERE)).replace('\\', '/'))
    save(fig, 'fig2_case_effects_and_fifo')
    (figdir / 'source_data.json').write_text(json.dumps(plotdata, ensure_ascii=False, indent=2), encoding='utf-8')
    with (HERE / 'metrics.csv').open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['case', 'question', 'cores', 'method', 'selected', 'makespan', 'reference_cycles',
                  'raw_speedup_vs_original_singlecore', 'same_plan_cache_gain', 'generation_seconds', 'plan_sha256']
        writer = csv.DictWriter(f, fields, extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)

    text = [f'全部 **{len(rows)}/{len(rows)}** 份方案通过官方验收。{len(labels)} 次开发标注与 {summary["official_acceptance_calls"]} 次验收调用分属两个阶段；验收阶段对完全相同的方案复用评分，仅避免重复计算。官方文件 {summary["official_files_unchanged"]} 份保持原始哈希，模型与推理代码均保持冻结。',
        '', '下表为 **6 个验证图** 的逐例加速比算术平均，参考值为同图原始单核完成时间。问题三最后一列单独统计同一方案开关 L2 的收益。', '',
        '| 核心数 | 问题一 | 问题二 | 问题三 | 问题三同方案 L2 收益 |', '|---:|---:|---:|---:|---:|']
    latex = ['% Generated from summary.json; SIX validation graphs, NOT full 100 cases.',
             '\\begin{tabular}{rrrrr}', '\\toprule', '核心数 & 问题一 & 问题二 & 问题三 & 同方案 L2 收益 \\\\', '\\midrule']
    for n in range(1, 6):
        values = [summary['questions'][str(q)][str(n)]['arithmetic_mean_speedup'] for q in (1, 2, 3)]
        gain = summary['questions']['3'][str(n)]['mean_same_plan_cache_gain']
        text.append('| '+ ' | '.join([str(n)] + [f'{v:.6f}' for v in values] + [f'{gain:.6f}']) + ' |')
        latex.append(' & '.join([str(n)] + [f'{v:.6f}' for v in values] + [f'{gain:.6f}']) + ' \\\\')
    latex += ['\\bottomrule', '\\end{tabular}', '% Table uses actual original-singlecore ratios. Required Q1/Q2 plot anchors n=1 at 1.']
    text += ['', '表中保留实际单核方案的原图参考比值；图 1 的问题一、二单核点按题意显示为 1。', '',
        '| 五核比较 | 问题一 | 问题二 | 问题三 |', '|---|---:|---:|---:|']
    five = [summary['questions'][str(q)]['5'] for q in (1, 2, 3)]
    text += ['| 相对单资源装箱的平均耗时降幅 | ' + ' | '.join(f'{r["mean_paired_makespan_reduction"]:.2%}' for r in five) + ' |',
             '| 改善 / 退步图数 | ' + ' | '.join(f'{r["improved"]} / {r["regressed"]}' for r in five) + ' |',
             '| 单图方案生成平均耗时（秒） | ' + ' | '.join(f'{r["mean_generation_seconds"]:.3f}' for r in five) + ' |', '',
        f'六图平均值受图结构影响明显，不代表百例总体。五核退步图数分别为 {five[0]["regressed"]}、{five[1]["regressed"]}、{five[2]["regressed"]}；第三问同方案 L2 平均收益为 **{summary["questions"]["3"]["5"]["mean_same_plan_cache_gain"]:.6f}**。基于这些证据，本轮未启动百例全量性能实验，也未把旧版全量成绩迁移到新协议。', '',
        '图 1 展示不同核数下的平均效果与同方案 Cache 收益；图 2 同时保留逐图退步点，并用实际 FIFO 事件解释命中与时间收益的区别。两图均由真实记录生成，未添加统计置信带。', '',
        '![不同核心数的效果](figures/fig1_core_scaling.png)', '',
        '![逐图效果与FIFO事件](figures/fig2_case_effects_and_fifo.png)', '']
    report = HERE / '三问模型与实验说明.md'; body = report.read_text(encoding='utf-8')
    start, end = '<!-- RESULTS_START -->', '<!-- RESULTS_END -->'
    report.write_text(body.split(start)[0] + start + '\n' + '\n'.join(text) + '\n' + end + body.split(end)[1], encoding='utf-8')
    (HERE / '验证结果表.tex').write_text('\n'.join(latex) + '\n', encoding='utf-8')
    print(json.dumps({'figures': 2, 'cases': 6, 'plan_acceptances': len(rows), 'full_100_case_performance_done': False}))


if __name__ == '__main__': main()
