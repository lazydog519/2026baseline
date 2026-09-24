# 2026 官方基线与问题一优化

当前快照：**1500/1500** 组评测成功，100 例已齐全。

`solution/` 是方案生成与评测代码；`results/summary.csv` 为已完成组合的真实官方评测摘要，`results/raw/` 保留相应方案及评测返回 JSON（gzip）。完整结果时另有逐例统计和图。

`project/` 保存 A 题项目目录的完整快照，`project/source_attachment/` 保存原始 A 题 DOCX/ZIP，`project/related_outputs/` 保存此前的 A 题导读和开源复用评估；不包含其他赛题和两套第三方仓库源码。运行中的结果仅在官方评测写入成功状态后复制。评测逻辑和配置未改动；详见 `技术思路稿-基线.md` 与 `original_runs/README.md`。

问题一优化：见 [`技术思路稿-问题一优化.md`](技术思路稿-问题一优化.md)、[`project/q1_optimization/final/`](project/q1_optimization/final/) 和 [`project/solution/q1_submit.py`](project/solution/q1_submit.py)。5 核逐例平均加速比为 **3.947986**。
