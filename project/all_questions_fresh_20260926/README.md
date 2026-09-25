# 三问统一冷启动求解：开发验证版 v2

本版遵循新的求解协议：**官方评估器只在开发标注和冻结后验收使用，最终推理完全不调用它。** 每个输入从头构造候选，只加载本轮学习的全局参数。无历史方案、逐 case 参数或成绩表。

已完成：100 图结构分析、三问机理与输出接口改造、140 份本轮开发标签、6 图 × 5 种核数 × 2 种方法 × 3 问的 **180 份方案验收**、说明稿、LaTeX 公式与两张数据图。所有方案通过官方验收。**尚未进行百例全量性能实验，不作为正式全量提交版。**

| 五核，6 个验证图 | 问题一 | 问题二 | 问题三 |
|---|---:|---:|---:|
| 原图单核参考下的平均加速比 | 2.492154 | 2.448958 | 2.461842 |
| 相对本轮单资源装箱的平均耗时降幅 | 10.93% | 8.29% | 8.40% |
| 出现退步的图数 | 2 | 1 | 2 |

第三问同一方案开关 L2 的平均加速比为 **1.006323**。不能用上表的第三问数值声称 Cache 加速约 2.46 倍，也不能与历史百例五核均值直接比较。当前收益主要集中在少数图；反例与薄弱环节见说明稿。

## 阅读入口

- [模型、算法与真实结果](三问模型与实验说明.md)
- [论文公式 LaTeX](模型与算法公式.tex)、[自动生成的验证结果表 LaTeX](验证结果表.tex)
- [冻结推理包](submission_solver.zip)：只有 `solver.py`、`mechanism.py`、`model.json`
- [逐方案指标 CSV](metrics.csv)、[汇总 JSON](summary.json)
- [不同核心数的效果](figures/fig1_core_scaling.pdf)、[逐图效果与 FIFO 实际事件](figures/fig2_case_effects_and_fifo.pdf)
- [输入结构分析](input_profiles.csv)、[样本与规则清单](manifest.json)、[边界搬运核对](boundary_audit.json)
- [冻结记录](generation_freeze.json)、[开发标签](training_labels.json)、[验证结果](validation_results.json)

## 独立生成方案

从仓库根目录运行，替换输入与输出路径即可。推理仅需 Python 3.10+ 标准库；在本机 Python 3.12 验证。原版配置文件必须保持字节不变。

```powershell
python project/all_questions_fresh_20260926/solver.py project/official/data/case_001.json -n 5 --question 1 --config project/official/data/config.txt --model project/all_questions_fresh_20260926/model.json -o answer_q1.json --report generation_q1.json
```

第二、三问分别把 `--question` 改为 `2`、`3`，并使用不同输出名。结果只有 `node_to_subgraph` 与 `core_schedules` 两个字段；观察记录写在独立文件中。`--method component_scalar` 是同输入的新建装箱对照，不读取历史解。

`submission_solver.zip` 解压后同样使用上述参数，只需修改脚本和模型路径。代码不需要与官方评估器放在一起。没有把最终推理换成官方模拟器的重命名副本：`mechanism.py` 明确使用近似排布和逻辑生命周期，其误差由独立验收揭示。

## 重现实验

开发与绘图另外需要 NumPy、Matplotlib。`experiment.py` 明确属于开发/验收工具，**不在推理包中**。该脚本从相邻 `official/` 读取题目附件，从本目录写入实验记录。重新开发请在 `project/` 下建立新空目录，仅复制本目录的五个 `.py` 源码（求解、机理、检查、实验、绘图）以及说明稿模板；不要复制历史模型、标签和冻结文件。下列步骤中的目录名相应替换为新目录，当前冻结目录会拒绝覆盖。

```powershell
python project/all_questions_fresh_20260926/checks.py
python project/all_questions_fresh_20260926/experiment.py prepare
python project/all_questions_fresh_20260926/experiment.py train --workers 4
python project/all_questions_fresh_20260926/experiment.py generate
python project/all_questions_fresh_20260926/experiment.py accept --workers 4
python project/all_questions_fresh_20260926/publish.py
```

阶段顺序为：核对题面/附录与哈希 → 小例检查 → 本轮标签 → 参数冻结 → 隔离冷启动生成 → 全部方案冻结 → 官方验收。已有标签仅在方案字节匹配时复用；它们属于本轮开发标签，不是旧项目成绩。

推理使用确定性顺序，没有随机种子和壁钟时间截断。检查脚本包含 FIFO 命中不刷新、重复填充、超容量张量、并发带宽、同核 Task 边界、跨核扇出重复写出和收缩成环等反例。`development_v1/` 仅保存正式验证前发现计量错误的开发版本，不能作为当前推理入口；其中 12000 次结构检查也不能代替实际存储与执行验收。

## 与 GitHub 历史版本的关系

整合时已快进到 `cf70431b`，保留 `q1_final_v1/`、`q2_final_v1/`、`q3_cold/` 等原文件。那些版本的全量成绩属于评估器参与候选选择的协议。本目录具有新的参数、代码哈希与验证样本，不继承其分数。

本次重用的是分量结构、双 Pipe 负载、共享输入亲和与合法顺序等一般算法知识。旧拟合权重和旧结果不进入求解；参考论文中的不成立界和不受支持的预热控制也没有带入模型。当前输入支持范围与不足详见说明稿，后续不能在未验证时宣称覆盖任意未知图或达到预设均值。
