"""Build readable editions from the three canonical LaTeX chapter fragments."""
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
FILES=[(int(n),ROOT/(v+'.tex')) for n,v in __import__('json').loads((ROOT/'章节结构.json').read_text(encoding='utf-8')).items()]


def argument(text, start):
    assert text[start]=='{'
    depth=1; i=start+1
    while depth:
        if text[i]=='{' and text[i-1]!='\\': depth+=1
        elif text[i]=='}' and text[i-1]!='\\': depth-=1
        i+=1
    return text[start+1:i-1],i


def inline(text):
    text=re.sub(r'\\textbf\{([^{}]+)\}',r'<strong>\1</strong>',text)
    text=re.sub(r'\\texttt\{([^{}]+)\}',lambda m:'<code>'+m[1].replace(r'\_','_')+'</code>',text)
    text=text.replace(r'COPY\_OUT','COPY_OUT').replace(r'COPY\_IN','COPY_IN')
    text=text.replace(r'case\_', 'case_').replace(r'\%', '%')
    refmap={r['key']:str(i) for i,r in enumerate(__import__('json').loads((ROOT/'references.json').read_text(encoding='utf-8')),1)}
    text=re.sub(r'\\cite\{([^}]+)\}',lambda m:''.join('['+refmap[k]+']' for k in m[1].split(',')),text)
    return text.replace('--','–')


def main():
    sources={n:p.read_text(encoding='utf-8') for n,p in FILES}
    eqs={}; figs={}; tabs={}
    for n,s in sources.items():
        for prefix,target,sep in [('eq:',eqs,'.'),('fig:',figs,'-'),('tab:',tabs,'-')]:
            for i,label in enumerate(re.findall(r'\\label\{('+prefix+r'[^}]+)\}',s),1):
                target[label]=f'{n}{sep}{i}'
    def equation(m):
        body=m[1];label=re.search(r'\\label\{([^}]+)\}',body)[1]
        body=re.sub(r'\\label\{[^}]+\}','',body).strip()
        return '\n\n$$\n'+body+'\n\\tag{'+eqs[label]+'}\n$$\n\n'
    def figure(m):
        block=m[0];path=re.search(r'\\includegraphics\[[^]]+\]\{([^}]+)\}',block)[1]
        cap,_=argument(block,block.index('{',block.index(r'\caption')))
        label=re.search(r'\\label\{([^}]+)\}',block)[1]
        return '\n\n<figure><img src="'+path.replace('.pdf','.png')+'" alt="图 '+figs[label]+'"><figcaption>图 '+figs[label]+'　'+cap+'</figcaption></figure>\n\n'
    def table(m):
        block=m[0];cap,_=argument(block,block.index('{',block.index(r'\caption')))
        label=re.search(r'\\label\{([^}]+)\}',block)[1]
        rows=[]
        start=block.index(r'\begin{tabular}')+len(r'\begin{tabular}')
        _,end=argument(block,start)
        for line in block[end:block.index(r'\end{tabular}')].splitlines():
            if '&' in line: rows.append([v.strip().rstrip('\\').strip() for v in line.split('&')])
        result=['<table><caption>表 '+tabs[label]+'　'+cap+'</caption><thead><tr>']
        result.extend('<th>'+v+'</th>' for v in rows[0]);result.append('</tr></thead><tbody>')
        result.extend('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows[1:])
        return '\n\n'+''.join(result)+'</tbody></table>\n\n'
    def algorithm(m):
        block=m[0];title,_=argument(block,block.index('{',len(r'\begin{algorithmblock}')))
        title=title.replace(r'\quad','　')
        result=['<div class="algorithm"><div class="algtitle">'+title+'</div>']
        for macro,label in [('alginput','输入'),('algoutput','输出')]:
            pos=block.index('{',block.index('\\'+macro));val,_=argument(block,pos)
            result.append('<div class="algio"><strong>'+label+'：</strong>'+val+'</div>')
        matches=list(re.finditer(r'\\algline(?:\[(\d+)\])?\{',block))
        for i,item in enumerate(matches,1):
            val,_=argument(block,item.end()-1); indent=int(item[1] or 0)
            result.append(f'<div class="algline"><span class="num">{i}.</span><span class="step" style="padding-left:{indent}em">'+val+'</span></div>')
        return '\n\n'+''.join(result)+'</div>\n\n'
    outputs=[]
    for n,s in sources.items():
        s=re.sub(r'\\begin\{equation\}(.*?)\\end\{equation\}',equation,s,flags=re.S)
        s=re.sub(r'\\begin\{figure\}\[htbp\].*?\\end\{figure\}',figure,s,flags=re.S)
        s=re.sub(r'\\begin\{table\}\[htbp\].*?\\end\{table\}',table,s,flags=re.S)
        s=re.sub(r'\\begin\{algorithmblock\}.*?\\end\{algorithmblock\}',algorithm,s,flags=re.S)
        s=re.sub(r'\\section\{([^}]+)\}',lambda m:'# 第'+{1:'一',2:'二',3:'三',4:'四',5:'五',6:'六',7:'七',8:'八',9:'九'}[n]+'章　'+m[1],s)
        count=[0]
        def sub(m):
            count[0]+=1;return f'## {n}.{count[0]}　'+m[1]
        s=re.sub(r'\\subsection\{([^}]+)\}',sub,s)
        for name,val in eqs.items():s=s.replace(r'\eqref{'+name+'}','（'+val+'）')
        for name,val in {**figs,**tabs}.items():s=s.replace(r'\ref{'+name+'}',val)
        s=s.replace('式~','式').replace('图~','图 ').replace('表~','表 ')
        s=inline(s)
        if any(x in s for x in (r'\label',r'\eqref',r'\ref{',r'\algline')):raise ValueError((n,re.findall(r'\\(?:label|eqref|ref|algline)\{[^}]+\}',s)))
        outputs.append(s.strip())
    references=__import__('json').loads((ROOT/'references.json').read_text(encoding='utf-8'))
    refs='\n\n<div class="references"><h2>参考文献</h2>'
    for i,r in enumerate(references,1): refs+='<p>['+str(i)+'] '+r['reference'].replace('--','–')+'</p>'
    refs+='</div>\n'
    abstract=(ROOT/'摘要.tex').read_text(encoding='utf-8')
    abstract=abstract[abstract.index(r'\end{center}')+len(r'\end{center}'):]
    title='<div class="paper-title">通用神经网络处理器的结构感知切图与分层调度模型</div>\n\n<h2 class="abstract-title">摘要</h2>\n\n'
    appendix='\n\n<h2>附录：结果与程序索引</h2>\n\n配套电子表保存前两问各400行和第三问500行逐图结果。单核参照、原始方案和验收记录随三问代码包提供；附录逐图结果.tex 可并入团队提交模板。\n'
    ai=(ROOT/'AI使用说明.tex').read_text(encoding='utf-8')
    ai=re.sub(r'\\subsection\*\{([^}]+)\}',r'<h2>\1</h2>',ai)
    appendix+='\n\n'+inline(ai)
    (ROOT/'整合修订稿.md').write_text(title+inline(abstract)+'\n\n'+'\n\n'.join(outputs)+refs+appendix,encoding='utf-8')
    print(f'equations={len(eqs)} figures={len(figs)} tables={len(tabs)} algorithms=4 chapters=9')

if __name__=='__main__':main()
