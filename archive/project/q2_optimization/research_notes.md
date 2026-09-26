# 问题二证据与方法来源（2026-09-24 核对）

正式题面 `第二十三届中国研究生数学建模竞赛 - 中文题目/中文题目/A题/通用神经网络处理器下的多核调度问题.docx`、原附件 `official/README.md`、`official/code/multicore_cut_evaluate_problem_2.py`、`schedule_step1.py`、`schedule_step2.py`、`schedule_step3.py` 和 `official/data/config.txt` 是输入、约束、单位与最终数值的第一依据。原始附件在本项目中未修改；每个候选须由原始场景 B 评测器计算。

外部检索使用内置 WebSearch，关键词包括 `DAG partitioning acyclic communication cost`、`HEFT original paper`、`MAGIS ASPLOS 2024`。本次工具列表没有可调用的 `mcp__search__search`，故未把它的缺席解释为没有相关研究。

| 资料 | 支持的设计或边界 | 本题实际采用方式 |
|---|---|---|
| [Topcuoglu、Hariri、Wu, *Performance-Effective and Low-Complexity Task Scheduling for Heterogeneous Computing* (IEEE TPDS, 2002)](https://disco.ethz.ch/courses/fs14/seminar/paper/Jochen/4.pdf) | 关键路径排序与最早完成时间是 DAG 调度的经典启发式 | 先前问题一候选含借鉴的 HEFT 排序；本题直接复评其合法方案，不采用原论文的异构机器耗时作为分数 |
| [dagP：Multilevel Directed Acyclic Graph Partitioner](https://github.com/GT-TDAlab/dagP) | DAG 切分需要同时顾及负载与跨分区通信 | 仅作方法学参照；没有将 dagP 原仓库当成附件评测器，也没有声称运行其输出 |
| [MAGIS（ASPLOS 2024）原仓库](https://github.com/pku-liang/MAGIS) | 内存与图调度需联合考虑 | 仅借鉴联合考虑的原则；MAGIS 允许的图变换超出本题输出接口，故本次不改任何原始算子或张量 |

图 10～12 是用户提供的思路建议，非正式题面。其跨核启发式表达式把 `size(x)`（bytes）与同步时间（cycles）直接相加，量纲不一致；可解释的周期代理至少需把字节除以 60 bytes/cycle，并说明并发共享 DDR 与多条等待的重叠使其不等于真实 Makespan。本次候选优劣只由官方评测器决定。图中 Tensor 生存期近似同样不充当容量合规证明；以官方 Step2/Step3 与 `memory_peak_by_core` 为准。
