# 2026 A题方案与验证

本轮新增：[三问统一冷启动开发版](project/all_questions_fresh_20260926/README.md)。三问最终推理均不调用官方评估器，仅携带本轮校准参数；6 个验证图、1—5 核的 180 份方案全部通过冻结后验收。提供[说明稿](project/all_questions_fresh_20260926/三问模型与实验说明.md)、[LaTeX 公式](project/all_questions_fresh_20260926/模型与算法公式.tex)、[代码包](project/all_questions_fresh_20260926/submission_solver.zip)、[两张结果图](project/all_questions_fresh_20260926/figures/)。

**这是小样本开发版，未完成百例全量性能验证，也未证明优于下列旧版全量算法。** 第一、三问仍各有两个五核退步样本，第二问有一个；问题三同方案 Cache 平均加速比为 1.006323。完整证据与不足均保留，不以历史均值替代新版本成绩。

以下保留历史全量实验记录。这些版本在求解中调用官方评估器选优，与上面的新协议不同。最新整理包另见 [Q1 Final v1](project/q1_final_v1/) 与 [Q2 Final v1](project/q2_final_v1/)；后者五核百例均值为 4.180461，与 `q2_cold` 的 4.246278 属于不同版本。

早期三问快照：**1500/1500** 组评测成功，100 例已齐全。

`solution/` 是方案生成与评测代码；`results/summary.csv` 为已完成组合的真实官方评测摘要，`results/raw/` 保留相应方案及评测返回 JSON（gzip）。完整结果时另有逐例统计和图。

`project/` 保存 A 题项目目录的完整快照，`project/source_attachment/` 保存原始 A 题 DOCX/ZIP，`project/related_outputs/` 保存此前的 A 题导读和开源复用评估；不包含其他赛题和两套第三方仓库源码。运行中的结果仅在官方评测写入成功状态后复制。评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。

问题一历史独立搜索版：从输入图独立求解，固定最多六次官方评估，不读取历史方案。见 [`技术思路稿-问题一独立求解.md`](技术思路稿-问题一独立求解.md)、[`results/q1_cold/`](results/q1_cold/)、[`论文公式`](project/q1_cold/模型与算法公式.tex) 和 [`独立代码包`](project/q1_cold/submission_q1.zip)。100 例 5 核平均加速比 **3.786386**。400 份最终方案已由原评估器逐份重新核验。

运行入口：`python project/solution/q1_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。旧 `q1_optimization/` 为历史离线选优，不作为当前独立求解成绩。

问题二历史独立搜索版：从输入图独立求解，不读取历史方案。见 [`技术思路稿-问题二独立求解.md`](技术思路稿-问题二独立求解.md)、[`results/q2_cold/`](results/q2_cold/) 和 [`独立代码包`](project/q2_cold/submission_q2.zip)。100 例 5 核平均加速比 **4.246278**。400 份最终方案已由原评估器重新核验。

运行入口：`python project/solution/q2_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。旧 `q2_optimization/` 为不同预算的历史离线实验，不作为当前独立求解成绩。

问题三历史独立搜索版：见 [`技术思路稿-问题三独立求解.md`](技术思路稿-问题三独立求解.md)、[`100 例逐核复核`](project/q3_cold/final/)、[`代码包`](project/q3_cold/submission_q3.zip) 和 [`结果图`](project/q3_cold/figures/)。100 例五核平均加速比 **4.395999**；500 份最终方案均由未改动的原评估器复核。运行入口：`python project/solution/q3_fusion_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。早期 `q3_fusion/branch_validation/` 仅为开发样本，不代表全量成绩。
