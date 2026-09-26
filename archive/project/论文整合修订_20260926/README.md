# 一至九章整合修订稿

从[整合修订稿.pdf](整合修订稿.pdf)阅读；[paper.tex](paper.tex)是可继续编辑的多文件LaTeX入口，章节和公式按统一符号整理。[整合修订稿.md](整合修订稿.md)供差异审阅。原前五章和旧六至八章均保留。

正文含摘要、9章、32个编号公式、10张图、9张表和4个算法框。额外提供完整[逐图结果长表](附录逐图结果.tex)，可按最终提交模板并入。

本轮重构第2–6.1节的承接关系，补充结构分析、模型约束、逐图比较和第三问递进解释。数据分析使用已冻结结果，三问五核均值仍为3.831066527、3.952170334、4.193922744，没有改分数或重新调参。

## 文件与复现

- `figures/`：10图PNG、PDF、SVG；`data/`：原始索引、图表明细、三问统计和哈希核对。
- `figures_and_checks.py`、`chapter8_figures.py`：只读取同项目已保存输入/结果并绘图；不调用官方评估器。
- `build_readable.py`、`render_readable.js`：从章节.tex生成Markdown/HTML/阅读PDF；需要现有Python、Node、marked、playwright/Edge和首次渲染可访问MathJax。保存HTML已内嵌数学SVG，离线阅读不依赖MathJax网络。
- `package_checks.py`：生成逐图长表并检查官方114文件、交叉引用和环境闭合。
- `复核记录/`：结构修订、参考文献支撑范围、内容与排版检查、AI辅助与提交准备。

图表和阅读PDF已检查；阅读PDF不等于团队模板的最终XeLaTeX编译结果。题目原文要求的逐例结果长表尚未并入阅读PDF，数据已完整提供。团队仍需审定内容、补充AI元数据、按竞赛模板完成排版再提交。

AI使用记录已按用户确认列入GPT 5.6 SOL、GPT 6、Claude。Claude具体型号/参与范围及模型发布日期待核实。本轮没有网络查重或AIGC检测，不提供任何通过率承诺。

内置 LaTeX 编译器本次返回环境错误 `Unable to find standard directories for platform`，没有完成原生编译；源码保留，PDF由既有同源阅读渲染流程生成。
