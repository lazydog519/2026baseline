# 最终协作包：论文、三问代码与图表

本协作项目建议命名：**华为杯A题｜最终论文与三问代码**。

只从本目录开始工作。历史实验留在 GitHub 的 `archive/`，无需下载或导入 Overleaf。

| 要做什么 | 文件/目录 |
|---|---|
| 编译论文 | `main.tex`；选择 **XeLaTeX** |
| 修改正文 | `sections/01.tex` 到 `sections/09.tex`，分别对应第1至9章 |
| 修改摘要或文献 | `sections/abstract.tex`、`sections/references.tex` |
| 运行最终算法 | `code/q1/solver.py`、`code/q2/solver.py`、`code/q3/solver.py` |
| 替换论文图 | `figures/fig6_1.pdf` 等；文件名与图号对应 |
| 重绘全部图片 | 本机运行 `python plots/replot.py` |
| 查看真实结果 | `data/两场景逐例结果.csv`、`data/问题三逐例配对结果.csv` |
| 查看工具披露和修改记录 | `docs/` |

三问核心源文件保持原始字节，五核均值仍为 **3.831066527 / 3.952170334 / 4.193922744**。没有增加求解阶段的官方评估器，也没有重跑全量调参。

## VS Code 本机编辑（当前入口）

打开仓库根目录 `华为杯A题.code-workspace`，按 **Ctrl+Alt+B** 编译、**Ctrl+Alt+V** 预览。三问运行和重绘图片通过“任务：运行任务”选择。两人实时协作使用 Live Share。[详细操作说明](docs/VSCode使用说明.md)。

## Overleaf 操作（可选）

1. 用自己的邮箱注册/登录 https://www.overleaf.com/project 。若学校有机构授权，优先使用学校邮箱。
2. 点击 **New Project → Upload Project**，选择提供的 `overleaf_project.zip`。不要上传整个 GitHub 仓库，也不必先解压。
3. 在项目设置中确认 **Main document = main.tex**、**Compiler = XeLaTeX**，点击 **Recompile**。
4. 点击 **Share**，输入队友邮箱并选择 **Can edit**。对方接受邀请后共同编辑。当前按两个人协作，即项目所有者加一位编辑者。不要共享账户密码。
5. 建议一人维护第1–5章，另一人维护第6–9章；摘要、文献和格式共同审定。讨论用评论，修改前保存一个版本标记（若账户支持）。

当前包没有创建公开编辑链接，也没有自动邀请任何人。上传项目本身不会把 GitHub 设为公开。

## 本机运行与图片更新

Python 求解只需标准库（建议 Python 3.10+），Overleaf 不运行这些 Python 程序。在包根目录打开终端：

```text
python verify.py --smoke
python code/q1/solver.py examples/case_001.json -n 5 --config code/config.txt -o work/q1.json
python code/q2/solver.py examples/case_001.json -n 5 --config code/config.txt -o work/q2.json
python code/q3/solver.py examples/case_001.json -n 5 --config code/config.txt -o work/q3.json
```

把示例路径换成任意符合题目格式的输入图即可。一次独立调用重新构造方案；输出保存后才可另行使用原版官方评估程序验收。`examples/` 中的期望输出只由 `verify.py` 比较，不传入求解器。

绘图需要 matplotlib、numpy 和可用中文字体，本机以宋体检查过。安装依赖后运行：

```text
python -m pip install -r plots/requirements.txt
python plots/replot.py
```

绘图只读取本包数据，生成10张 PDF 和PNG，不访问历史实验目录。论文引用矢量PDF；重绘后把新的同名PDF上传至 Overleaf 的 `figures/` 覆盖即可。无需为修改文字重新运行算法。

## 统一工作版本

当前以 **VS Code 本地文件和 GitHub 提交** 作为工作版本。通过 Live Share 可共同编辑主机文件；阶段结束后提交并推送到 GitHub。Overleaf 项目独立保留，没有配置自动双向同步；若网页已有新修改，先导出源文件再合并，避免覆盖。

## 排版与提交

本工程采用可跨平台编译的 `ctexart + Fandol` 中文字体配置，属于协作稿。它包含正文和摘要，不含官方封皮。最终提交还需核对官方宋体/黑体、封皮、匿名要求、AI工具版本与发布日期；不因“成功编译”就声称已满足所有提交条件。

`sections/results_appendix.tex` 保存1300行逐例长表，默认不并入正文以缩短协作编译。需要正式并入时取消 `main.tex` 底部相应 `input` 的注释。已完成的正式结果和历史原始记录仍保留在归档。

官方帮助（核对2026-09-26）：
- ZIP导入：https://docs.overleaf.com/managing-projects-and-files/uploading-a-project
- 协作权限：https://docs.overleaf.com/collaborating/sharing-a-project
- 免费与付费功能：https://docs.overleaf.com/getting-started/free-and-premium-plans
