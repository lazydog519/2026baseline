"""Convert the canonical Chapter 6 LaTeX fragment to a complete readable Markdown."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "第六章_问题一与问题二建模求解.tex"
TARGET = ROOT / "第六章_直观阅读版.md"


def main():
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace("--", "–")
    eq_names = re.findall(r"\\label\{(eq:[^}]+)\}", text)
    eq_map = {name: f"6.{i}" for i, name in enumerate(eq_names, 1)}
    fig_map = {
        "fig:chapter6-mechanism": "6-1",
        "fig:chapter6-speedup": "6-2",
        "fig:chapter6-copy": "6-3",
        "fig:chapter6-box": "6-4",
    }

    def equation(match):
        kind, body = match.group(1), match.group(2)
        label = re.search(r"\\label\{(eq:[^}]+)\}", body)
        if not label:
            raise ValueError("unnumbered chapter equation")
        number = eq_map[label.group(1)]
        body = re.sub(r"\\label\{eq:[^}]+\}", "", body).strip()
        if kind == "align":
            body = r"\begin{aligned}" + "\n" + body + "\n" + r"\end{aligned}"
        return f'\n\n<a id="{label.group(1)}"></a>\n\n$$\n{body}\n\\tag{{{number}}}\n$$\n\n'

    text = re.sub(r"\\begin\{(equation|align)\}(.*?)\\end\{\1\}",
                  equation, text, flags=re.S)

    def figure(match):
        image, caption, label = match.groups()
        if label not in fig_map:
            raise ValueError(f"unmapped figure: {label}")
        number = fig_map[label]
        image = image.replace("论文第六章/figures/", "figures/").replace(".pdf", ".png")
        return (f'\n\n<a id="{label}"></a>\n\n'
                f'![图 {number}](<{image}>)\n\n'
                f'*图 {number}　{caption}*\n\n')

    text = re.sub(
        r"\\begin\{figure\}\[htbp\]\s*\\centering\s*"
        r"\\includegraphics\[[^\]]+\]\{([^}]+)\}\s*"
        r"\\caption\{([^}]+)\}\s*\\label\{([^}]+)\}\s*\\end\{figure\}",
        figure, text, flags=re.S)

    def algorithm(match):
        block = match.group(0)
        title = re.search(r"\\textbf\{(算法\s*[12]\\quad[^}]+)\}", block)
        io = re.search(r"\\textbf\{输入：\}(.*?)\\textbf\{输出：\}(.*?)\\par",
                       block, flags=re.S)
        enumeration = block.split(r"\begin{enumerate}", 1)[1]
        enumeration = re.sub(r"\\setlength\{\\itemsep\}\{[^}]+\}",
                             "", enumeration)
        items = re.findall(r"\\item\s*(.*?)(?=\\item|\\end\{enumerate\})",
                           enumeration, flags=re.S)
        tail = block.split(r"\end{enumerate}", 1)[-1]
        tail = re.sub(r"\\vspace\{[^}]+\}|\\hrule|\\end\{minipage\}|\\end\{center\}|\}",
                      "", tail).strip()
        if not title or not io or len(items) < 4:
            raise ValueError("algorithm box conversion failed")
        name = title.group(1).replace(r"\quad", "　")
        lines = [f"> **{name}**", ">",
                 f"> **输入：**{io.group(1).strip()}　"
                 f"**输出：**{io.group(2).strip()}"]
        lines.extend([">", *[f"> {i}. {' '.join(item.split())}"
                               for i, item in enumerate(items, 1)]])
        lines.extend([">", f"> {tail}"])
        return "\n\n" + "\n".join(lines) + "\n\n"

    text = re.sub(
        r"\\begin\{center\}\s*\\centering\s*\\fbox\{\\begin\{minipage\}.*?"
        r"\\end\{minipage\}\}\s*\\end\{center\}",
        algorithm, text, flags=re.S)

    def table(match):
        block = match.group(0)
        caption = re.search(r"\\caption\{([^}]+)\}", block).group(1)
        tab = re.search(r"\\begin\{tabular\}\{[^}]+\}(.*?)\\end\{tabular\}",
                        block, flags=re.S).group(1)
        rows = []
        for line in tab.splitlines():
            if "&" in line:
                rows.append([x.strip().rstrip("\\").strip() for x in line.split("&")])
        if len(rows) != 6 or any(len(row) != 5 for row in rows):
            raise ValueError("result table conversion failed")
        lines = ["**表 6-1　" + caption + "**", "",
                 "| " + " | ".join(rows[0]) + " |",
                 "|:---:|---:|---:|---:|---:|"]
        lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
        return "\n\n" + "\n".join(lines) + "\n\n"

    text = re.sub(r"\\begin\{table\}\[htbp\].*?\\end\{table\}",
                  table, text, flags=re.S)
    text = re.sub(r"(?m)^%.*\n?", "", text)
    text = re.sub(r"\\section\{([^}]+)\}", r"# 第六章　\1", text)
    text = re.sub(r"\\subsection\{([^}]+)\}", r"## \1", text)
    text = re.sub(r"\\subsubsection\{([^}]+)\}", r"### \1", text)
    text = re.sub(r"\\texttt\{([^}]+)\}",
                  lambda m: chr(96) + m.group(1).replace(r"\_", "_") + chr(96), text)
    text = re.sub(r"\\emph\{([^}]+)\}", r"*\1*", text)
    for label, number in fig_map.items():
        text = text.replace(r"图~\ref{" + label + "}", "图 " + number)
    for label, number in eq_map.items():
        text = text.replace(r"\eqref{" + label + "}", "（" + number + "）")
    text = text.replace("式~", "式")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if any(x in text for x in (r"\begin{figure}", r"\begin{table}",
                               r"\begin{center}", r"\begin{enumerate}",
                               r"\ref{", r"\label{")):
        raise ValueError("LaTeX environment or reference remains in Markdown")
    header = (
        "> 本版与 LaTeX 正文共用同一模型和官方结果，供直接阅读；"
        "公式编号、图号与正文对应。图中所有性能量均由冻结方案经原版评估程序取得，"
        "规则示意图不表示实测时长。单核加速比按题意定义为 1。\n\n"
    )
    TARGET.write_text(header + text + "\n", encoding="utf-8")
    print(TARGET, "equations", len(eq_map), "figures", len(fig_map))


if __name__ == "__main__":
    main()
