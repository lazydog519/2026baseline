"""Code-only Q1 archive and isolated real-input reproduction check."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',type=Path,required=True)
    a=ap.parse_args();p=a.project.resolve();archive=p/'q1_cold/submission_q1.zip'
    manifest=json.loads((p/'q1_cold/frozen_manifest.json').read_text())
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,digest in manifest['files'].items():
            f=p/'solution'/name
            assert hashlib.sha256(f.read_bytes()).hexdigest()==digest
            z.write(f,'solution/'+name)
        for f in sorted((p/'official/code').glob('*.py')):z.write(f,'official/code/'+f.name)
        z.write(p/'official/data/config.txt','config.txt')
        z.write(p/'q1_cold/frozen_manifest.json','frozen_manifest.json')
        z.writestr('README.md',
            '# 问题一独立求解代码包\n\nPython 3.12 已验证，求解仅依赖标准库。输入图需另行提供。\n\n'
            '`python solution/q1_submit.py graph.json -n 5 --config config.txt -o graph_multicore_res.json`\n\n'
            '每次从当前图重新构造候选，至多六次官方评估；不读取历史答案、成绩或其他用例。'
            '2～5 核输出 JSON 仅含 node_to_subgraph 与 core_schedules；1 核基准按题意单独计算。'
            '诊断写入相邻的 *_search 目录，每次评估后落盘。计数上限不等于运行秒数上限。\n\n'
            '独立复核：`python official/code/multicore_cut_evaluate_problem_1.py graph.json graph_multicore_res.json --config config.txt`。'
            '附录原评估器与固定配置未改动。\n')
    with tempfile.TemporaryDirectory(prefix='q1_submission_') as tmp:
        root=Path(tmp)
        with zipfile.ZipFile(archive) as z:z.extractall(root)
        shutil.copy2(p/'official/data/case_036.json',root/'renamed_input.json')
        subprocess.run([sys.executable,'-X','utf8',str(root/'solution/q1_submit.py'),str(root/'renamed_input.json'),
                        '-n','5','--config',str(root/'config.txt'),'-o',str(root/'answer.json')],
                       cwd=root,check=True,capture_output=True)
        answer=json.loads((root/'answer.json').read_text())
        reference=json.loads((p/'q1_cold/full/case_036/n5/case_036_multicore_res.json').read_text())
        assert answer==reference and set(answer)=={'node_to_subgraph','core_schedules'}
        run=json.loads((root/'answer_search/run.json').read_text())
        assert run['cold_start'] and not run['history_read']
    result=dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),archive_bytes=archive.stat().st_size,
                isolated_renamed_real_input=True,matches_frozen_full_run=True,historical_result_files_in_archive=False,
                real_case='case_036',makespan_cycles=run['makespan_cycles'])
    (archive.parent/'package_verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
