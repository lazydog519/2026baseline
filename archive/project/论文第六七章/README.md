# 第六章、第七章

[直接阅读 PDF](第六七章_阅读版.pdf) · [离线 HTML](第六七章_阅读版.html) · [第六章 LaTeX](第六章_问题一.tex) · [第七章 LaTeX](第七章_问题二.tex)

第六章只讨论问题一，第七章只讨论问题二。两章按输入结构分析、数学模型、算法步骤、求解结果的顺序展开。算法框采用编号、循环缩进与黑色细线；正文包含三幅图，不再使用彩色卡片。

## 代码与文字对应

| 内容 | 冻结代码中的实现 |
|---|---|
| 操作依赖、拓扑序、深度与结构切分 | `q1_priority_20260926/q1_optimized.py` |
| 分量分解、双管道负载装箱 | `q1_priority_20260926/baseline.py` 的 `make_plan` |
| 问题一时间估计、就绪调度、相邻合并 | `q1_priority_20260926/mechanistic.py` |
| 问题一候选集合与 1% 保留规则 | `q1_priority_20260926/solver.py` 和 `policy.json` |
| 问题二分支层间距、五类候选、通信估计 | `q2_priority_20260926/final_v2/model.py` |
| 问题二张量区间与缓存风险 | `q2_priority_20260926/final_v2/memory_proxy.py` |
| 问题二固定评分与选择 | `q2_priority_20260926/final_v2/solver.py` |

算法框按逻辑依赖顺序归纳输入分析；源程序在模型初始化与候选构造函数中按需提取这些特征。它不是按 case 编号查表，也没有新增图类型分类器。本次不改变上述冻结求解代码，只重算结构统计、汇总现有官方结果并重写论文；原始文件 SHA-256 已与两问验收摘要核对。

## 符号与证据

| 符号 | 定义 | 单位 |
|---|---|---|
| `G`、`G_c` | 原始图、非 COPY 操作依赖视图 | — |
| `phi`、`a`、`pi_k` | 子图映射、核心分配、每核子图序列 | — |
| `c_u`、`b_t` | 操作周期、张量字节数 | cycle、byte |
| `beta` | 各核共享的 DDR 总带宽 | byte/cycle |
| `delta_same`、`delta_cross`、`delta_B` | 场景 A 同核/跨核等待、场景 B 同步延迟 | cycle |
| `C_r`、`H_k^r`、`R_B` | 缓存容量、静态区间峰值、风险量 | byte |
| 带帽的 `T`、`B` | 求解中的排序估计 | cycle、byte |
| `T_iN`、`S_iN` | 官方验收时间、由单核参照计算的加速比 | cycle、无量纲 |

结构表来源为 [100 例输入特征](data/100例结构特征.csv)。三幅图的结果来自[两场景逐例结果](data/两场景逐例结果.csv)和[统计摘要](data/统计摘要.json)，每场景 400 组，均为成功的官方验收记录。单核曲线值按定义置 1，未新增单核实验。图 7-1 仅示意题目机制，不表示实测排队长度、驻留曲线或 FIFO 服务顺序。

写作借鉴所提供材料的章节次序、公式解释方式和算法框形式，未采用其无依据的零溢出结论、数值或近似保证。LPT 与列表调度的来源分别核对于 [SIAM](https://epubs.siam.org/doi/10.1137/0117039) 和 [IEEE](https://ieeexplore.ieee.org/document/993206/)。正文明确区分本题改写与原算法，不将多资源系统直接套入经典 LPT 近似比。

## 复现与排版

依次运行 `analyze_and_plot.py`、`build_readable.py`、`render_readable.js` 可重建图表、Markdown、HTML 与阅读 PDF。图表使用 Python/Matplotlib，输出 PNG、PDF、SVG；源码与输入保持不变。HTML 的公式已保存为 SVG，可离线阅读。

`paper.tex` 为 XeLaTeX 入口；整合到正式论文时，可引入两章正文，并保留其算法框宏定义。当前环境没有本地 TeX 引擎，交付 PDF 由同一正文转换后排版，已经逐页检查；不把它标为 XeLaTeX 编译成功的提交稿。
