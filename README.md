# 2026 A题方案与验证

最新论文修订：[第八章 PDF](project/论文第六至八章/第八章_问题三_阅读版.pdf)、[第六至八章合并 PDF](project/论文第六至八章/第六至八章_修订稿.pdf)、[LaTeX、图表及口径核对](project/论文第六至八章/README.md)。保留原稿与冻结算法，修正三章符号、伪代码和结果解释；第八章补充共享 Cache 数据通路、全量配对收益与实际 FIFO 驻留轨迹。

初始三问评测归档：**1500/1500** 组评测成功，100 例已齐全。

当前提交入口和成绩以以下各问说明为准。根目录 `solution/` 保留初始实验代码；`results/summary.csv` 为初始已完成组合的真实官方评测摘要，`results/raw/` 保留相应方案及评测返回 JSON（gzip）。完整结果时另有逐例统计和图。

`project/` 保存 A 题项目目录的完整快照，`project/source_attachment/` 保存原始 A 题 DOCX/ZIP，`project/related_outputs/` 保存此前的 A 题导读和开源复用评估；不包含其他赛题和两套第三方仓库源码。运行中的结果仅在官方评测写入成功状态后复制。评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。

问题一当前提交版：从每个原图独立生成方案，推理过程不调用官方评估器。见 [`方法与实验稿`](project/q1_priority_20260926/问题一方法与实验稿.md)、[`公式`](project/q1_priority_20260926/模型与算法公式.tex)、[`独立代码包`](project/q1_priority_20260926/submission_q1.zip)、[`官方逐例结果`](project/q1_priority_20260926/full_metrics.csv) 和 [`论文图`](project/q1_priority_20260926/figures/)。100 例五核平均加速比 **3.831067**；2～5 核共 400 份冻结方案通过原版评估。旧 `q1_cold/` 使用评估器在求解时挑选候选，标记为历史结果。

问题二当前提交版：同核子图合并、DDR 通信与驻留风险联合筛选；每个图从头求解，推理时不调用官方评估器。见 [`方法与复现说明`](project/q2_priority_20260926/README.md)、[`独立代码包`](project/q2_priority_20260926/final_v2/submission_q2.zip)、[`官方逐例结果`](project/q2_priority_20260926/final_v2/full_metrics.csv) 和 [`论文第六章`](project/论文第六章/第六章_问题一与问题二建模求解.tex)。100 例五核平均加速比 **3.952170**；2～5 核共 400 份冻结方案通过原版评估。旧 `q2_cold/` 在求解过程中调用官方评估器选优，为历史结果。

问题三当前提交版：每个输入图从头构造和比较至多十种方案；求解不调用官方评估器，不读取历史解。见 [`算法与复现`](project/q3_adaptive_20260926/README.md)、[`独立代码包`](project/q3_adaptive_20260926/submission_q3.zip)、[`权威全量结果`](project/q3_adaptive_20260926/final/)、[`论文、公式与伪代码`](project/论文第六章/问题三建模与求解.tex)、[`收益图`](project/论文第六章/figures/图6-5_第三问逐核收益与搬运.pdf) 和 [`缓存机理图`](project/论文第六章/figures/图6-6_第三问缓存复用与时序.pdf)。100 图五核平均加速比 **4.193923**；1～5 核共 500 份冻结方案完成 1000 次配对官方验收。给定 100 图参与过开发诊断，这不是完全未见数据的泛化成绩。旧 `q3_cold/` 使用求解中官方选优，保留为历史，不能混用其分数。
