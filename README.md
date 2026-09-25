# 2026 A题方案与验证

当前快照：**1500/1500** 组评测成功，100 例已齐全。

`solution/` 是方案生成与评测代码；`results/summary.csv` 为已完成组合的真实官方评测摘要，`results/raw/` 保留相应方案及评测返回 JSON（gzip）。完整结果时另有逐例统计和图。

`project/` 保存 A 题项目目录的完整快照，`project/source_attachment/` 保存原始 A 题 DOCX/ZIP，`project/related_outputs/` 保存此前的 A 题导读和开源复用评估；不包含其他赛题和两套第三方仓库源码。运行中的结果仅在官方评测写入成功状态后复制。评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。

问题一当前提交版：从输入图独立求解，固定最多六次官方评估，不读取历史方案。见 [`技术思路稿-问题一独立求解.md`](技术思路稿-问题一独立求解.md)、[`results/q1_cold/`](results/q1_cold/)、[`论文公式`](project/q1_cold/模型与算法公式.tex) 和 [`独立代码包`](project/q1_cold/submission_q1.zip)。100 例 5 核平均加速比 **3.786386**。400 份最终方案已由原评估器逐份重新核验。

运行入口：`python project/solution/q1_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。旧 `q1_optimization/` 为历史离线选优，不作为当前独立求解成绩。

问题二当前提交版：从输入图独立求解，不读取历史方案。见 [`技术思路稿-问题二独立求解.md`](技术思路稿-问题二独立求解.md)、[`results/q2_cold/`](results/q2_cold/) 和 [`独立代码包`](project/q2_cold/submission_q2.zip)。100 例 5 核平均加速比 **4.246278**。400 份最终方案已由原评估器重新核验。

运行入口：`python project/solution/q2_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。旧 `q2_optimization/` 为不同预算的历史离线实验，不作为当前独立求解成绩。

问题三当前结构算法：见 [`论文方法稿`](project/q3_fusion/第三问-分支分离与缓存协同-论文方法稿.md)、[`独立代码包`](project/q3_fusion/q3_branch_code_only.zip)、[`配对实验与复核`](project/q3_fusion/branch_validation/) 和 [`可视化`](project/q3_fusion/figures/)。所选 7 例、5 核、每例 3 种子的等预算配对缩短率均值 **25.78%**；这不是 100 例或 1～5 核的全量成绩。
