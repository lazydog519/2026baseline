# 问题一：独立冷启动的图结构切分与 Task 调度

本目录只处理场景 A。官方题目和附件优先；`official/`、原图和固定配置未修改。`solver.py` 是最终推理入口，仅加载当前图、`config.txt`、固定的 `policy.json` 和本目录纯求解模块，不导入官方评估器，不读取历史方案或成绩。每个 case/核数由一个新进程生成，输出恰好 `node_to_subgraph` 与 `core_schedules`。单核不用该求解器；论文单核加速比按题意为 1。

模型包含双 Pipe 分量装箱、图深/汇合/共享关系切分、就绪 Task 贪心排核与有界合并。候选只按解析代理评价；该代理不等同于官方时间线，L1/UB 溢出的准确搬运量由冻结后官方验收取得。并列规则曾在开发图中暴露退步，现固定为：代理收益不超过 1% 时保留分量装箱。该阈值是经验防抖参数，不是正确性证书。

开发资料：`development/` 八图 127 候选，`holdout/` 四图 65 候选；`sample_summary.json` 说明小样本的改善与退步。全量方案和哈希记录在 `full_plans/` 与 `full_generation_manifest.json`，共有 100×4 份。`full_audit.py` 在全部方案冻结之后，才调用原版场景 A 评估器；成功时生成 `full_metrics.csv`、`full_summary.json`。`diagnostic_v1/` 是发现并列规则错误时封存的旧诊断，**不是当前方案**，不应用于论文或提交。

独立推理命令（`-n` 取 2～5）：

```powershell
python solver.py PATH_TO_CASE.json -n 5 --config PATH_TO_CONFIG.txt -o case_multicore_res.json --policy policy.json
```

`submission_q1.zip` 只含五个纯求解文件。`package_verification.json` 记录两个图在隔离目录、改名输入上的相同方案复现。`develop.py`、`full_audit.py`、历史结果、官方程序均不在提交包内。方法解释见 `问题一方法与实验稿.md`，可直接引用的数学符号见 `模型与算法公式.tex`。论文图仅在完整 400 次官方验收后由 `figures.py` 从真实数据生成。
