# VS Code 本机使用说明

打开仓库根目录的 `华为杯A题.code-workspace`。左侧只列出最终项目，历史实验仍在仓库 archive/ 中。

## 改正文和看 PDF

1. 打开 `main.tex`，按 **Ctrl+Alt+B** 编译论文。默认使用已安装的 Tectonic，原有 Overleaf 的 XeLaTeX 注释不影响本机配置。
2. 按 **Ctrl+Alt+V** 打开右侧 PDF 预览，输出文件为 `_build/main.pdf`。
3. 分章节修改 `sections/01.tex` 至 `sections/09.tex`，保存后自动编译。正常编译只需几秒；无需运行算法。

若 VS Code 首次显示“工作区信任”提示，请核对这是自己的项目后自行选择；未信任时扩展可能受限。编译报错时打开底部“输出”，选择 LaTeX Workshop 查看原因。

## 运行代码和重绘图片

通过 **Ctrl+Shift+P → Tasks: Run Task（任务：运行任务）** 选择 Q1/Q2/Q3，输入 JSON 路径并选择 2–5 核。默认示例是 `examples/case_001.json`。

结果写入 `work/q1_latest.json` 等文件，同一问再次试跑会替换 latest 文件；计算过程记录为 `work/q1_report.json` 等。正式历史结果保存在 data/ 和仓库归档中。本轮没有修改求解器，也没有把官方评估器加入求解入口。

“重绘论文全部图片”任务使用 plots/ 和包内数据更新 figures/ 的 10 张图片；“校验冻结代码与数据”检查 SHA256；“三问隔离输入复现检查”执行三问的小规模复现。

## 两人协作

已安装 Live Share。你与队友都使用 VS Code；由你点击 Live Share，按页面指引登录 GitHub 或 Microsoft 账号，再开始共享，把邀请链接发给队友。队友接受后可共同修改本机工作区中的文件。本轮没有替你登录或创建共享会话。

实时协作期间，你的电脑、VS Code 和网络需要保持可用。异步协作可改用私有 GitHub 的提交与拉取；不要把网页 Overleaf 的改动视为已自动同步。本次本地工程来自 GitHub 最新 V2；如已在 Overleaf 修改过正文，先从网页导出再合并。

## 本机配置位置

编译器路径和 Python 路径集中在 `.vscode/settings.json`，三问任务引用这里的 Python 配置。当前设置适配本机；队友若独立克隆运行，需要把两个路径换成其电脑上的 Tectonic 与 Python。Live Share 的共同编辑不要求队友安装同一编译环境。

`.vscode/` 和工作区文件可以同步到 GitHub；`_build/`、`work/` 是本机生成物，已排除。协作期以本地/GitHub 版本为主，不启用双向自动覆盖。

官方说明：
- LaTeX Workshop 编译与快捷键：https://github.com/James-Yu/LaTeX-Workshop/wiki/Compile
- Live Share 协作：https://learn.microsoft.com/en-us/visualstudio/liveshare/quickstart/share
