# 2026 A 题：问题一、二独立求解与第三问方法验证

历史三问基础实验：**1500/1500** 组评测成功。后续改进各自的完成范围见下文，第三问新方法尚未全量验证。

`solution/` 是方案生成与评测代码；`results/summary.csv` 为已完成组合的真实官方评测摘要，`results/raw/` 保留相应方案及评测返回 JSON（gzip）。完整结果时另有逐例统计和图。

`project/` 保存 A 题项目目录的完整快照，`project/source_attachment/` 保存原始 A 题 DOCX/ZIP，`project/related_outputs/` 保存此前的 A 题导读和开源复用评估；不包含其他赛题和两套第三方仓库源码。运行中的结果仅在官方评测写入成功状态后复制。评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。

问题一当前提交版：从输入图独立求解，固定最多六次官方评估，不读取历史方案。见 [`技术思路稿-问题一独立求解.md`](技术思路稿-问题一独立求解.md)、[`results/q1_cold/`](results/q1_cold/)、[`论文公式`](project/q1_cold/模型与算法公式.tex) 和 [`独立代码包`](project/q1_cold/submission_q1.zip)。100 例 5 核平均加速比 **3.786386**。400 份最终方案已由原评估器逐份重新核验。

运行入口：`python project/solution/q1_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。旧 `q1_optimization/` 为历史离线选优，不作为当前独立求解成绩。

问题二当前提交版：从输入图独立求解，不读取历史方案。见 [`技术思路稿-问题二独立求解.md`](技术思路稿-问题二独立求解.md)、[`results/q2_cold/`](results/q2_cold/) 和 [`独立代码包`](project/q2_cold/submission_q2.zip)。100 例 5 核平均加速比 **4.246278**。400 份最终方案已由原评估器重新核验。

运行入口：`python project/solution/q2_submit.py 输入图.json -n 5 --config project/official/data/config.txt`。旧 `q2_optimization/` 为不同预算的历史离线实验，不作为当前独立求解成绩。

第三问当前为**方法与小样本验证**：7 例 × 1/2/5 核，共 21 组；采用同一方案有/无 L2 配对。确认组三例五核比值均值 **1.007435**，不是全量或多核对单核的均值。4 个事件反馈候选未胜出，尚不声称该局部策略有效。114 份官方文件未修改，独立改名输入复现通过。

见 [第三问论文方法稿](project/q3_design/第三问论文方法稿.md)、[公式](project/q3_design/模型与算法公式.tex)、[纯代码包](project/q3_design/q3_prototype_code.zip)、[21 组结果](project/q3_design/pilot_metrics_all.csv) 与 [两幅图表](project/q3_design/figures/)。未启动全量优化。

第三问新增 **NSGA-III / U-NSGA-III 的 NPU 离散适配测试**：3 例、固定 5 核、3 种子、3 方法，共 27 次独立搜索；每次同为 30 次原评估。加入拆分、合并、通信亲和迁移及拓扑修复。工程组并非稳定占优，保留全部负结果；未全量运行。见 [设计与三组结果](project/q3_nsga/README.md)、[代码包](project/q3_nsga/q3_nsga_code.zip)、[均值与范围](project/q3_nsga/summary.csv)、[搜索过程](project/q3_nsga/convergence.png)。
