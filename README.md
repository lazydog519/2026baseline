# 2026 A题方案与验证

当前快照：**1500/1500** 组评测成功，100 例已齐全。

`solution/` 是方案生成与评测代码；`results/summary.csv` 为已完成组合的真实官方评测摘要，`results/raw/` 保留相应方案及评测返回 JSON（gzip）。完整结果时另有逐例统计和图。

`project/` 保存 A 题项目目录的完整快照，`project/source_attachment/` 保存原始 A 题 DOCX/ZIP，`project/related_outputs/` 保存此前的 A 题导读和开源复用评估；不包含其他赛题和两套第三方仓库源码。运行中的结果仅在官方评测写入成功状态后复制。评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。

问题一当前提交版：从每个原图独立生成方案，推理过程不调用官方评估器。见 [`方法与实验稿`](project/q1_priority_20260926/问题一方法与实验稿.md)、[`公式`](project/q1_priority_20260926/模型与算法公式.tex)、[`独立代码包`](project/q1_priority_20260926/submission_q1.zip)、[`官方逐例结果`](project/q1_priority_20260926/full_metrics.csv) 和 [`论文图`](project/q1_priority_20260926/figures/)。100 例五核平均加速比 **3.831067**；2～5 核共 400 份冻结方案通过原版评估。旧 `q1_cold/` 使用评估器在求解时挑选候选，标记为历史结果。

问题二当前提交版：同核子图合并、DDR 通信与驻留风险联合筛选；每个图从头求解，推理时不调用官方评估器。见 [`方法与复现说明`](project/q2_priority_20260926/README.md)、[`独立代码包`](project/q2_priority_20260926/final_v2/submission_q2.zip)、[`官方逐例结果`](project/q2_priority_20260926/final_v2/full_metrics.csv) 和 [`论文第六章`](project/论文第六章/第六章_问题一与问题二建模求解.tex)。100 例五核平均加速比 **3.952170**；2～5 核共 400 份冻结方案通过原版评估。旧 `q2_cold/` 在求解过程中调用官方评估器选优，为历史结果。

第六章另有可直接阅读的 [PDF](project/论文第六章/第六章_直观阅读版.pdf)、[离线 HTML](project/论文第六章/第六章_直观阅读版.html) 和 [阅读说明](project/论文第六章/第六章_阅读说明.md)；正文的四张图依次解释硬件数据通路、平均加速比、DDR 搬运和逐图分布。

问题三独立提交版：见 [`技术思路稿-问题三独立求解.md`](技术思路稿-问题三独立求解.md)、[`100 例逐核复核`](project/q3_cold/final/)、[`代码包`](project/q3_cold/submission_q3.zip) 和 [`结果图`](project/q3_cold/figures/)。100 例五核平均加速比 **4.395999**；500 份最终方案均由未改动的原评估器复核。运行入口：`python project/solution/q3_fusion_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。早期 `q3_fusion/branch_validation/` 仅为开发样本，不代表全量成绩。
