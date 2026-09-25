# 第三问：分支分离与共享 FIFO 缓存

从 [论文方法稿](第三问-分支分离与缓存协同-论文方法稿.md) 开始读；公式可直接取用
[LaTeX 片段](模型与算法公式.tex)。这次完成的是 **7 个所选案例 × 5 核 × 3
种子** 的小样本、等预算验证，尚未跑 100 例 × 1～5 核，不应当作最终比赛均值。

主要发现：一个大子图在删去局部入口后可能分成多个独立计算分支。允许这些分支
分核，即使新增 COPY，也可能同时释放并行度，并改变读取进入共享 FIFO L2
的时机。固定每次独立搜索 30 次官方评测，新方法对 21 个配对运行胜 20、平 1，
配对缩短率均值 25.78%；069、086 两个算子冻结后验证例分别缩短 21.7%、
27.5%。074 已接近计算下界，改进仅 0.5%。所有值来自原问题三评测器。

- `branch_solver.py`：分支分离算子，与原事件引导邻域及 U-NSGA-III
  参考方向选择结合；`branch_experiment.json`：实验预算与随机种子。
- `submit.py`：代码单独运行的提交入口，默认生成
  `<输入名>_multicore_res.json`，仅有题目规定的两个字段。
- [纯代码包](q3_branch_code_only.zip) 含原评测器代码和固定配置，不含案例输入、
  旧方案或历史结果；[清单](code_package_manifest.json) 记录 SHA-256。
  已在隔离目录对**改名输入**重跑，输出与开发环境同种子完全一致。
- [逐运行指标](branch_validation/metrics.csv)、[逐例汇总](branch_validation/case_summary.csv)、
  [验证信息](branch_validation/verification.json) 与 [冻结文件哈希](branch_validation/manifest.json)：
  42 个最终方案独立重算题三，并成对运行无 L2 的题二。
- [单操作机理证据](branch_validation/mechanism.json)：044 的一次分支分离
  使 73,728 B 张量的后续四次读取在首次填充后命中；
  [分离前方案](branch_validation/mechanism_parent_plan.json) 与
  [分离后方案](branch_validation/mechanism_child_plan.json) 可独立重评。
- [配对效果图](figures/paired_reduction.png) 与
  [FIFO 事件图](figures/fifo_window_case044.png)，同时提供 PDF；仅这两张
  用于正文。

在项目根目录安装 `numpy`、`pymoo==0.6.1.6` 后，可调用：

~~~powershell
python q3_fusion/submit.py official/data/case_069.json -n 5 --seed 17
python official/code/multicore_cut_evaluate_problem_3.py official/data/case_069.json official/data/case_069_multicore_res.json --config official/data/config.txt
~~~

该求解器对每个输入从原图构造种群，题三评测从空 L2 开始；不读取仓库中的候选
方案作初值。同一个案例内部的进化个体会保留，这属于算法搜索，不是跨案例或
跨运行热启动。包内 `submit.py` 不含任何已生成方案。完整 100 例及 1～5 核
曲线需另行全量验证。
