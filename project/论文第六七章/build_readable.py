"""Convert the two canonical chapter fragments to one readable Markdown file."""
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
FILES=[(6, ROOT/'第六章_问题一.tex'),(7, ROOT/'第七章_问题二.tex')]


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
    text=text.replace(r'\cite{Graham1969}','<sup>[1]</sup>').replace(r'\cite{Topcuoglu2002}','<sup>[2]</sup>')
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
        for line in re.search(r'\\begin\{tabular\}\{[^}]+\}(.*?)\\end\{tabular\}',block,re.S)[1].splitlines():
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
        s=re.sub(r'\\section\{([^}]+)\}',lambda m:'# 第'+('六' if n==6 else '七')+'章　'+m[1],s)
        count=[0]
        def sub(m):
            count[0]+=1;return f'## {n}.{count[0]}　'+m[1]
        s=re.sub(r'\\subsection\{([^}]+)\}',sub,s)
        for name,val in eqs.items():s=s.replace(r'\eqref{'+name+'}','（'+val+'）')
        for name,val in {**figs,**tabs}.items():s=s.replace(r'\ref{'+name+'}',val)
        s=s.replace('式~','式').replace('图~','图 ').replace('表~','表 ')
        s=inline(s)
        if any(x in s for x in (r'\label',r'\eqref',r'\ref{',r'\algline')):raise ValueError('unconverted reference')
        outputs.append(s.strip())
    refs='''\n\n<div class="references">
<h2>参考文献</h2>

<p>[1] Graham R L. Bounds on Multiprocessing Timing Anomalies. SIAM Journal on Applied Mathematics, 1969, 17(2): 416–429. <a href="https://doi.org/10.1137/0117039">DOI: 10.1137/0117039</a>.</p>

<p>[2] Topcuoglu H, Hariri S, Wu M Y. Performance-effective and low-complexity task scheduling for heterogeneous computing. IEEE Transactions on Parallel and Distributed Systems, 2002, 13(3): 260–274. <a href="https://doi.org/10.1109/71.993206">DOI: 10.1109/71.993206</a>.</p>
</div>
'''
    (ROOT/'第六七章_阅读版.md').write_text('\n\n'.join(outputs)+refs,encoding='utf-8')
    print(f'equations={len(eqs)} figures={len(figs)} tables={len(tabs)} algorithms=2')


if __name__=='__main__':main()
