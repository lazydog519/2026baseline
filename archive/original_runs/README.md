# 两套原仓库的本机复现记录

这些运行用于确认仓库在本机可执行、核对借鉴边界；它们的模型和数值均不是 A 题成绩。A 题成绩只取附件原始评测器。

## MAGIS

- 仓库：[pku-liang/MAGIS](https://github.com/pku-liang/MAGIS)，检出 `a332abc73dca97f769054c4f61aef0a52009cf34`，位置 `D:\huawei_a_2026\MAGIS`。
- 独立环境：`D:\huawei_a_2026\venv`，PyTorch 2.5.1+cu118；本机 NVIDIA GeForce RTX 3050 Ti Laptop GPU。
- 运行：`D:\huawei_a_2026\venv\Scripts\python.exe -X utf8 output\A题三问求解\original_runs\magis\reproduce.py`。调用原仓库 `simple_mlp_net`、`TorchCudaBackend`、`RelaxOptimizer`，结果在 `magis/result.json`，完整输出在 `magis/run.log`。
- 原检出在 Windows/Python 3.12 的循环导入中 `FissionOp` 注解抛出 `NameError`。`magis/windows_compat.patch` 仅给 `op_graph.py` 加延迟注解；运行脚本在导入完成后绑定 `FissionOp`。仓库算法未改。
- 该小规模 GPU 示例的实测延迟有运行噪声；`result.json` 同时保存初始、搜索后实测值与内部模拟值，不能把内部模拟值当作 A 题周期。

## Timeloop

- 仓库：[NVlabs/timeloop](https://github.com/NVlabs/timeloop)，v1.0 检出 `9f9b713a23dfab425da2a6dd0a162a1d70a1adae`，位置 `D:\huawei_a_2026\timeloop_original\repo`。
- 用仓库源码、仓库自带的 `pat-public` 和 MSYS2 UCRT64 C++ 工具链构建 `timeloop-model.exe`。构建脚本留在 `timeloop/build_native.py`；原仓库的 Windows 平台兼容改动留在 `timeloop/windows_compat.patch`，主要是 64 位整数容器赋值与 POSIX 信号 API。`timeloop-mapper` 因 `open_memstream` 未在此 Windows 工具链提供，本次未构建；已成功构建并运行原仓库的 `timeloop-model`。
- 原仓库 `configs/model/sample.cfg` 算术单元未写明 `meshX`，本机运行时会触发 mesh 断言。实验输入 `timeloop/sample_windows.cfg` 仅在 arithmetic 处显式加入 `meshX = 16`，以匹配其 256 实例的 16×16 网格。运行命令是在 `timeloop` 目录中执行 `D:\huawei_a_2026\timeloop_original\build_native\timeloop-model.exe sample_windows.cfg`，且 `PATH` 先加入 `D:\huawei_a_2026\timeloop_original\msys64\ucrt64\bin`。
- 实际结果：`timeloop/timeloop-model.stats.txt` 中 Cycles 100352、Utilization 0.06、Energy 170.82 uJ；控制台输出在 `timeloop/run.log`。这是卷积工作负载的 Timeloop 模型值，不能与 A 题图的周期相互替代。

两库均不直接读取 A 题 JSON。MAGIS 的图变换和 Timeloop 的张量索引/映射搜索要求题目未开放或未提供的信息，本阶段不把两库输出冒充赛题基线。
