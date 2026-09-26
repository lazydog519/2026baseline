# 三问独立冷启动推理试验包

这是本轮工程邻域方法的**试验版**，尚未完成 100 图 × 1—5 核 × 三问的原版执行验收，不能冒称最终提交成绩。它对每张输入图重新生成拓扑带、迁移、低通信割口拆分和交换候选；不读取历史方案、分数或官方评估器。模型参数只来自本轮六张开发图，按场景分别冻结。

环境：Python 3.12、NumPy。命令示例：

```bash
python inference.py case_057.json -n 5 --question 1 --config config.txt --output plan.json --report report.json
```

`--question` 为 1、2 或 3。问题一、二只对 2—5 核切图求解；单核曲线点直接取题目规定的整图单核基准。第三问若需要 1 核无／有 L2 对照，入口直接生成一个整图子图，不进行候选搜索。`plan.json` 只含 `node_to_subgraph` 和 `core_schedules`，`report.json` 记录图、配置和模型哈希、候选数、选用方法、生成用时；没有官方评估分数。配置必须是本轮冻结时的原版 `config.txt`。

`inference.py`、`candidate_family.py`、`graph_primitives.py`、`stage_candidates.py`、`structural_neighbors.py`、`mechanism.py`、`fast_fifo.py`、`selection_policy.py` 和 `model.json` 是完整推理依赖。`fast_fifo.py` 以每个传输池的累积服务量和完成阈值堆计算 FIFO 请求事件，替代逐事件扫描全部并发传输；100 个固定随机种子的微型踪迹与原解析实现一致。上级目录的开发脚本和标签没有纳入本包。隔离目录中仅保留这些文件、改名后的输入图和配置，12 份方案与先于官方验收冻结的方案哈希逐一一致；见上级目录 `standalone_verification.json`。输入约束、适用范围和失败风险见上级目录 `设计与检验口径.md`。
