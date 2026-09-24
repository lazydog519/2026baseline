# 问题一算法资料与使用边界（2026-09-24）

正式规则以本项目 `official/` 所对应的原题、附件代码和 `official/data/config.txt` 为准。网上算法仅启发候选方案；数值结果一律由附件原版 `evaluate_scene_a` 产生，未复制第三方代码或把第三方实验数字当作本题成绩。

| 一手资料 | 可借鉴内容 | 本题采用方式与边界 |
|---|---|---|
| [HEFT 原始论文](https://doi.org/10.1109/71.993206)、[Python 实现示例](https://github.com/mackncheesiest/heft) | DAG 上行优先级与预计最早完成时间 | 对已经合法切出的 **Task** 做核心分配和队列排序；不更改官方 Step1–3 对 Task 内 Op 的确定性顺序。任务权重与通信代价只是生成候选方案的代理量，最终以官方评测为准。 |
| [dagP](https://github.com/GT-TDAlab/dagP) | 有向无环切图及通信代价意识 | 借鉴“切图仍须无环”的设计原则；未集成仓库代码。 |
| [dag-partitioning](https://github.com/pxanthopoulos/dag-partitioning) | DAG 分块时考虑边界通信和内存 | 仅作为方法对照；该工具的数据格式与本题不同，不能直接产出官方两字段方案。 |
| [MAGIS](https://github.com/pku-liang/MAGIS) | 图调度与内存权衡 | 原仓库复现记录见 `../original_runs/README.md`；本题禁止为优化而改写原始计算图，因此未直接使用其图变换结果。 |

检索范围包括 DAG 分区、HEFT、通信代价与多核调度的 GitHub 仓库及原始论文。未找到可直接符合本题 Task/DDR/L1/UB 固定评测口径的现成求解器；这只是本次检索覆盖范围内的观察，不表示不存在此类工具。
