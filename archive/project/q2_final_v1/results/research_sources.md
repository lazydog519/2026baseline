# Q2 方法调研摘记

检索日期：2026-09-25。以下是一手论文/官方工程文档；借鉴其调度原则，不直接搬用其硬件假设或性能结论。

1. Yi et al., “A Cache-aware DAG Scheduling Method on Multicores: Exploiting Node Affinity and Deferred Executions,” *Journal of Systems Architecture* 2025, 103372, DOI: [10.1016/j.sysarc.2025.103372](https://doi.org/10.1016/j.sysarc.2025.103372). 作者提出亲和优先级与竞争感知分配，指出 locality 要与可用核心及竞争一起考虑。本项目把相邻生产/消费 Tensor 在同核上的边字节数记为局部亲和，并用它对候选搜索优先级排序。未声称复现 CADE 算法或其论文结果。
2. Lakhotia et al., “GPOP: A Cache- and Work-efficient Framework for Graph Processing Over Partitions,” 2018, [arXiv:1806.08092](https://arxiv.org/abs/1806.08092). 以分区粒度增加访问局部性，并在 communication modes 间做解析权衡；本项目借鉴分区/通信联合考量，不移植其图算法实现。
3. OpenXLA, [From HLO to Thunks: Scheduling and Buffer Assignment](https://openxla.org/xla/hlo_to_thunks). 官方编译器文档说明先按张量生命周期控制内存峰值、再尝试隐藏通信延迟，并在内存超预算时考虑 rematerialization。本赛题没有 XLA 的编译/硬件语义，本项目只借鉴“性能与峰值内存需联合评估”的工程原则。
4. OpenXLA, [Latency Hiding Scheduler cost model](https://openxla.org/xla/lhs_cost_model). 描述结合测量性能表与解析成本模型；本项目候选代理只用于排序，最终接受方案仍由题目原官方模拟器给出。

`0.85` 是本项目人为固定的 locality target（局部边字节比例），不是上述论文的理论阈值或调参得出的最优点。搜索优先考虑达到目标的候选；官方 spill bytes 与真实 Makespan负责最终判定。
