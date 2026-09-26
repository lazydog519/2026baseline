# 第三问方法与小样本验证

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
