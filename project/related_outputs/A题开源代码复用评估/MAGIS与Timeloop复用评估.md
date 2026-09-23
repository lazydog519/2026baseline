# MAGIS 与 Timeloop：A 题代码复用评估

核对日期：2026-09-23。范围：原始题面、赛题附件接口，以及两个项目的 README、论文摘要与引言、选定核心代码和许可证。没有安装项目依赖、运行其优化器或开展赛题性能实验。以下“适合程度”是静态代码审查判断，不是跑分结果。

结论：优先借鉴 MAGIS 的候选搜索组织方式，保留赛题原有评测器；Timeloop 用于理解数据复用和存储层次，暂不作为题三实现依赖。“MAGIS 对应问题 1+2、Timeloop 对应问题 3”只能表示主题相关，不能理解为接口、决策范围和模拟规则已经匹配。

## 1. 保存的材料

本目录 `sources` 保存了 29 个精选源码、说明与许可证文件，以及两篇原始论文；不是完整仓库，也不是已安装的 Python 包。未下载模型权重、训练数据或安装包。

| 项目 | 本次读取的固定提交 | 许可证 |
|---|---|---|
| [MAGIS](https://github.com/pku-liang/MAGIS) | `a332abc73dca97f769054c4f61aef0a52009cf34` | MIT |
| [Timeloop](https://github.com/NVlabs/timeloop) | `32370826fdf1aa3c8deb0c93e6b2a2fc7cf053aa` | BSD-3-Clause |

每个项目下的 `source-metadata.json` 记录提交，`tree.json` 记录仓库文件清单；`download-manifest.json` 和 `paper-manifest.json` 记录下载来源、文件大小与 SHA-256。后续引用源码应定位到这些提交，避免远端更新造成行号漂移。

论文：

- Chen 等，*MAGIS: Memory Optimization via Coordinated Graph Transformation and Scheduling for DNN*，ASPLOS 2024，DOI [10.1145/3620666.3651330](https://doi.org/10.1145/3620666.3651330)。本地 `sources/MAGIS-paper.pdf`，15 页。本次阅读前两页的摘要、研究动机和方法概述，未复现论文实验。
- Parashar 等，*Timeloop: A Systematic Approach to DNN Accelerator Evaluation*，ISPASS 2019，[作者全文](https://parashar.org/ispass19.pdf)。本地 `sources/Timeloop-paper.pdf`，12 页。本次阅读前两页；当前仓库另含后续扩展，不能把 2019 年论文当作现有全部功能的说明。

## 2. 赛题的复用边界

A 题输入已经是分块后的 Tensor–Op 计算图；操作的 `pipe`、`cycles`、张量 `size` 和依赖均已给定。选手输出只有：

```text
node_to_subgraph：每个非 COPY_IN/COPY_OUT 操作属于哪个子图
core_schedules：各核心上的子图顺序
```

因此可调整子图划分、核心分配和同核次序；不能借外部优化器改变原始运算、复制计算节点、重新选择算子分块、改写 cycles 或修改评测配置。子图合并是调度分组，不等于将多个原始算子改成一个新算子。

附件负责边界 COPY、核内访问排布、必要换入换出、Pipe 顺序与全局事件模拟。外部工具可以帮助产生候选方案，但其自带的延迟估计不能替代本题 Makespan。

本地依据：题面 §1.2—1.5、附录 B—D；附件 `README.md` 第 19—42、80—93 行；`code/stub_multicore_cut_and_schedule.py` 第 105—175 行。基础方案校验不等于完整执行可行性校验，最终仍需经过对应问题的评估入口。

## 3. MAGIS：搜索结构值得借鉴，主要图变换不能直接搬入

MAGIS 同时研究张量存活时间、张量形状与性能之间的关系。它允许重计算、换入换出和 Fission Transformation（拆分运算及张量）。其中 Fission 不等于赛题“把已有操作分到几个子图”。前者可改图，后者保留原始计算和依赖。这是最重要的适用范围差异。

### 值得阅读的代码位置

| 代码位置（相对 MAGIS 仓库） | 核对到的行为 | 本题怎样使用 |
|---|---|---|
| `python/magis/optimizer.py`，`RelaxOptimizer`，第 203—337 行 | 候选优先队列、已访问集合、评价、保留最好状态、时间和迭代限制 | 借鉴搜索流程；候选改为合法切图与调度方案，评价改接赛题程序 |
| 同文件第 210—229 行 | 内存限制、延迟限制对应不同排序；无两者限制时先比较内存再比较延迟 | 必须按本题 Makespan 主指标重写比较逻辑，不能照搬默认内存优先规则 |
| 同文件第 245、255—262 行 | 用 `graph.digest` 判断重复状态 | 必须按完整方案去重：同一原图可以有不同分组、分核和顺序，原图哈希不能区分它们 |
| `python/magis/scheduler.py`，`RpoScheduler`、`RefineMemOpRpoScheduler`，第 25—159 行 | 拓扑排布及 store/load/rematerialization 位置处理 | 可参考存活期与访问次序的关系；不能把所得操作序列直接当作本题提交格式，也不能替换规定的核内算法 |
| `python/magis/transform/mutator.py`，`SwapRematMutator.select_swap_remat_candidates`，第 199—229 行 | 从内存峰值时刻仍驻留的张量中找候选 | 可借鉴“先找造成压力的数据”这一诊断方法；它生成的换入换出和重计算变换不直接移植 |
| `python/magis/simulator.py`，`AsyncSimulator`，第 210—238 行 | 按计算/内存操作区分两类流，累加操作 latency | 缺少本题每核四条 Pipe、各场景同步和动态共享带宽语义，不能替代赛题模拟器 |
| `python/magis/testing/bench.py` 第 33—41 行 | 示例入口创建 `TorchCudaBackend` 并做硬件测量 | 不是读取赛题 JSON 后即可输出方案的接口；不需要为了借鉴搜索流程而安装整套 CUDA 实验环境 |

固定版本源码入口：[optimizer.py](https://github.com/pku-liang/MAGIS/blob/a332abc73dca97f769054c4f61aef0a52009cf34/python/magis/optimizer.py)、[scheduler.py](https://github.com/pku-liang/MAGIS/blob/a332abc73dca97f769054c4f61aef0a52009cf34/python/magis/scheduler.py)、[simulator.py](https://github.com/pku-liang/MAGIS/blob/a332abc73dca97f769054c4f61aef0a52009cf34/python/magis/simulator.py)、[mutator.py](https://github.com/pku-liang/MAGIS/blob/a332abc73dca97f769054c4f61aef0a52009cf34/python/magis/transform/mutator.py)。

额外注意：`scheduler.py` 第 162 行把 `IncScheduler` 标记为 `DEPRECATED`。不能因论文强调增量调度，就认定仓库里这个类应作为首选生产接口。项目存在 `always_simulation` 分支，所以“所有使用方式都必须有 GPU”也不准确；准确说法是 README 的现成实验入口与 CUDA 后端绑定，脱离它需要适配。

对三问的价值判断：

- 问题 1：搜索结构有用，但评价必须包含一个子图一个 Task、边界 DDR 搬运和 100/1000 周期等待。同核不同子图也不能默认免通信。
- 问题 2：存活期、同核数据复用的思想更贴近本题。但仍要保留每核 L1/UB 各自容量、跨核 500 周期等待以及 Pipe 约束。同核子图次序不等于额外添加整子图完成屏障。
- 问题 3：同一套外层搜索结构也能使用，换接题三评测入口即可评估候选；不需要因为进入第三问就更换为另一套大型框架。

这里“可复用”主要是方法和局部结构可改造，不是 `import magis` 后直接求本题。Python 的 `heapq`、集合与计时工具已足以承载这部分通用结构；重建 MAGIS 的图表示、后端和变换系统可能比编写小型适配搜索器更费事。

## 4. Timeloop：存储分析相关，但与题三的接口和时序不匹配

Timeloop 主要通过张量计算映射和架构模型分析数据流、性能及能耗。它的映射空间含循环分块、次序和空间分配；本题给定细粒度计算图后只开放分组、分核和子图次序。二者虽然都涉及存储，决策层次并不相同。[项目说明](https://github.com/NVlabs/timeloop/blob/32370826fdf1aa3c8deb0c93e6b2a2fc7cf053aa/README.md)

### 三个具体不匹配点

1. **输入信息不同。** Timeloop 常规 problem 格式需要计算维度、维度大小和输入输出张量的索引投影关系。本题的字节大小与周期数不能唯一还原这些信息；把 `size` 人为当作某一维度会引入未经题面支持的假设。[官方输入文档](https://timeloop.csail.mit.edu/v4/input-formats/problem)
2. **代价模型不同。** 检查的 `src/model/buffer.cpp::ComputePerformance` 第 2476—2623 行，聚合访问量、计算带宽需求并按瓶颈得到 slowdown 和 cycles。本题则在操作发射/结束事件上更新并发搬运与共享带宽。因此，配置相同容量和带宽，不足以保证两者给出相同 Makespan。[固定版本代码](https://github.com/NVlabs/timeloop/blob/32370826fdf1aa3c8deb0c93e6b2a2fc7cf053aa/src/model/buffer.cpp#L2476)
3. **题三具有明确的 Cache 事件语义。** 只有 COPY_IN 查询共享只读 Cache，按逻辑张量 ID 判断；未命中后在搬运完成时装入，FIFO 淘汰，命中不刷新顺序；DDR 与 Cache 使用两个独立共享带宽池。不能用一般的复用次数或 buffer 容量估计替代这套规则。在本次检查的主路径中，没有找到可直接接收赛题方案并实现上述全部规则的接口；这不等于断言整个 Timeloop 生态绝不可能扩展实现它。

由第三点可知，两个核心都读取同一张量，并不自动表示第二次读取能命中。若两次请求都发生在首次装入完成前，它们仍可能都未命中。反过来，为等待命中而推迟计算，也未必缩短全局结束时间。这里只解释机制，未据此断言某种策略更优。

本地代码依据：`multicore_cut_evaluate_problem_3.py` 第 539—558 行在发射时判断命中并记录统计，第 570—581 行选择带宽池；具体缓存装入/淘汰由其完成事件路径处理。题三仍保留问题 2 的计算依赖和跨核同步规则。

### 仍然有价值的部分

- `doc/mapper.md`：候选搜索、无效候选处理和停止条件，可作为实现思路参考；其 `timeout` 是连续无效候选计数，不是墙钟秒数。
- `src/search/hybrid.cpp`：针对 IndexFactorization 等映射维度的搜索，和本题的子图方案数据结构耦合方式不同，直接移植收益有限。
- `orojenesis/README.md` 与 [Orojenesis 官方说明](https://timeloop.csail.mit.edu/orojenesis)：研究缓存容量与数据搬运界之间的关系，也涉及多个张量运算的融合。适合作为背景阅读；将其界用于本题前仍需证明两者计算和存储假设一致。

当前仓库确实包含 `fused-workload`、`fused-mapping` 与 Orojenesis 等扩展，所以不能简单说“Timeloop 只能研究一个算子”。本次暂不接入的依据是输入、决策和时序规则不同，而不是忽略这些扩展。

## 5. 建议保留的实现关系

```text
赛题原始计算图和固定配置
           ↓
产生、调整候选：分组／分核／同核次序
（可借鉴 MAGIS 的搜索组织方式）
           ↓
完整方案去重 + 赛题合法性检查
           ↓
对应问题的原始评测器
           ↓
以 Makespan 为主比较，记录搬运、缓存等辅助指标
           ↓
保存最优合法方案及其可复现记录
```

候选调整方式本身尚未实现、比较或确定。后续若进入求解，才需要选择并验证具体的划分与调度策略。上图仅说明外部代码应接在哪里，不声称已有可用求解器。

| 复用对象 | 当前建议 |
|---|---|
| 赛题的 IO、基础方案校验、三个评测入口 | 优先复用原有实现 |
| MAGIS 的候选队列、去重、预算与最优状态保存 | 参考结构，围绕赛题方案改写必要部分 |
| MAGIS 的图变换、重计算、现成 CUDA 实验流程 | 不接入本题的正式方案生成路径 |
| Timeloop 的整套模型与 mapper | 暂不安装和集成 |
| Timeloop/Orojenesis 的复用与存储分析 | 留作理论背景，适用性另外验证 |

题三结果解释应继续保留已发现的统计口径差异：附件 `data_movement_bytes` 先按计划 COPY 统计，缓存命中后没有扣减；不能将该字段直接叫作缓存过滤后的真实 DDR 流量，更不能用另一个工具的统计替换它。

## 6. 引用和验证

源码复制或修改需保留相应版权和许可文本；Timeloop 的 BSD-3-Clause 另有限制以原作者名称背书的条款。论文方法引用与代码许可是两件事：借鉴方法要引用论文，改用代码要记录源文件、提交与改动。[MAGIS 许可证](https://github.com/pku-liang/MAGIS/blob/a332abc73dca97f769054c4f61aef0a52009cf34/LICENSE)、[Timeloop 许可证](https://github.com/NVlabs/timeloop/blob/32370826fdf1aa3c8deb0c93e6b2a2fc7cf053aa/LICENSE)

目前没有性能结论。后续验证至少应区分：方案合法性；沿用同一输入、配置和评测器的对照；算法实际生成时间；方案模拟 Makespan。不能把 MAGIS 或 Timeloop 论文中的效果数字当作本队在本题上的收益，也不能把“仓库质量高”替换成“赛题适配度高”。
