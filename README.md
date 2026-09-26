# 华为杯 A 题：最终论文与三问代码

协作入口已整理为 `final/`。它包含最新版 V2 正文、三问冻结算法、10 张论文图、重绘脚本和对应数据；历史实验统一保存在 `archive/`。

| 入口 | 用途 |
|---|---|
| [VS Code 工作区](华为杯A题.code-workspace) · [使用说明](final/docs/VSCode使用说明.md) | 当前本机入口：编译、PDF 预览、三问运行与两人协作 |
| [下载 Overleaf 项目 ZIP](downloads/overleaf_project.zip) | 登录 Overleaf 后选择 New Project → Upload Project，上传此文件 |
| [查看已编译论文 PDF](downloads/paper_preview.pdf) | 25 页协作稿，本机真实编译并检查排版 |
| [最终包与两人协作说明](final/README.md) | 文件分工、运行方式、图表更新及 Overleaf 设置 |
| [第1–9章 LaTeX](final/sections) | 在 Overleaf 按章节共同编辑 |
| [三问算法](final/code) | q1/q2/q3 各有独立 solver.py 入口 |
| [论文图片](final/figures) · [绘图代码](final/plots) | PDF 用于论文，PNG 用于查看；重绘只读取本包数据 |
| [正式结果数据](final/data) | 逐例结果、结构统计及来源核对 |
| [历史资料](archive) | 官方附件、原版复现和开发实验，不导入 Overleaf |

五核 100 例均值：问题一 **3.831066527**，问题二 **3.952170334**，问题三 **4.193922744**。本轮仅整合文件与排版，未修改算法或实验数值。

已核对：16 份冻结求解文件原始字节一致；三问在隔离目录中对改名输入重新求解，与冻结方案一致，求解未调用官方评估器；10 张图已用包内数据重绘；归档中的 114 个官方文件保持原始字节。

Overleaf 中选择 **main.tex / XeLaTeX**。当前包按两人协作编排；项目所有者通过 Share 邀请一位队友。Python 程序仍在本机运行。本文档不代表已在 Overleaf 创建项目；实际导入完成前，以下载包为交付物。

原始目录结构保存在标签 [archive-before-overleaf-20260926](https://github.com/lazydog519/2026baseline/tree/archive-before-overleaf-20260926)。归档是移动目录，未重写 Git 历史；日常查看无需打开历史实验。

本工程是论文协作稿。官方封皮、最终字体及 AI 工具完整披露仍由队伍提交前核对。
