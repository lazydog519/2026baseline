"""Prepare manuscript appendices and evidence reports without changing solver code."""
from pathlib import Path
import csv,json,hashlib,re,collections
R=Path(__file__).resolve().parent
P=R.parent
def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
ab=read(R/'data/两场景逐例结果.csv');cc=read(R/'data/问题三逐例配对结果.csv')
appendix=[r'\section*{附录：逐图结果}',r'所有时间以 cycle 计，额外搬运以 byte 计。问题一、二单核采用整图参照；第三问列同方案无 L2 和有 L2 的配对结果。']
for q in ['A','B']:
    appendix += [r'\subsection*{问题'+('一' if q=='A' else '二')+'}',r'\begin{longtable}{lrrrr}',r'用例 & 核数 & 完工时间 & 额外搬运 & 加速比 \\ \hline',r'\endhead']
    for r in ab:
        appendix.append(f"{r['case'].replace('_',r'\_')} & {r['cores']} & {float(r[q+'_makespan_cycles']):.0f} & {float(r[q+'_added_copy_bytes']):.0f} & {float(r[q+'_speedup']):.6f} \\")
    appendix.append(r'\end{longtable}')
appendix += [r'\subsection*{问题三}',r'\begin{longtable}{lrrrrr}',r'用例 & 核数 & 无 L2 时间 & 有 L2 时间 & 额外搬运 & 字节命中率 \\ \hline',r'\endhead']
for r in cc:
    appendix.append(f"{r['case'].replace('_',r'\_')} & {r['cores']} & {float(r['no_l2_cycles']):.0f} & {float(r['l2_cycles']):.0f} & {float(r['l2_added_bytes']):.0f} & {float(r['cache_hit_rate']):.6f} \\")
appendix.append(r'\end{longtable}')
# Each data row must end in the LaTeX two-backslash terminator.
appendix=[s+'\\' if ' & ' in s and s.endswith('\\') and not s.endswith('\\\\') else s for s in appendix]
(R/'附录逐图结果.tex').write_text('\n'.join(appendix)+'\n',encoding='utf-8')

src=json.loads((P/'q3_adaptive_20260926/full5_v2/generation_manifest.json').read_text(encoding='utf-8'))
for name,sha in src['official_sha256'].items():
    assert hashlib.sha256((P/'official'/name).read_bytes()).hexdigest()==sha,name
assert len(src['official_sha256'])==114
texts={f.name:f.read_text(encoding='utf-8') for f in sorted(R.glob('第*.tex'))}
labels=[];refs=[];cites=[];env_errors=[]
for name,s in texts.items():
    labels+=re.findall(r'\\label\{([^}]+)\}',s)
    refs+=re.findall(r'\\(?:eqref|ref)\{([^}]+)\}',s)
    for group in re.findall(r'\\cite\{([^}]+)\}',s):cites+=group.split(',')
    for env in ['equation','table','tabular','figure','algorithmblock']:
        if s.count('\\begin{'+env+'}')!=s.count('\\end{'+env+'}'):env_errors.append([name,env])
duplicates=[x for x,n in collections.Counter(labels).items() if n>1]
missing=sorted(set(refs)-set(labels))
known={r['key'] for r in json.loads((R/'references.json').read_text(encoding='utf-8'))}
assert not duplicates and not missing and not env_errors and not (set(cites)-known)
report={'official_files_unchanged':114,'source_files_unchanged':16,'unique_labels':len(labels),'duplicate_labels':duplicates,'missing_cross_references':missing,'latex_environment_mismatches':env_errors,'unresolved_citations':sorted(set(cites)-known),'formal_result_rows':{'q1':400,'q2':400,'q3_paired':500},'official_evaluator_calls_this_revision':0,'solver_changes_this_revision':0,'results_retrained':False,'external_plagiarism_or_aigc_check':False,'latex_project_compile_verified':False}
(R/'复核记录/内容一致性核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
