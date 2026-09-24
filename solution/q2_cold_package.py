"""Build and verify a code-only submission archive, with no historical results."""
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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path,required=True)
    args=parser.parse_args()
    p=args.project.resolve()
    archive=p/"q2_cold"/"submission_q2.zip"
    names=["q2_submit.py","q2_cold.py","q2_cold_config.json","q1_optimized.py","baseline.py"]
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name in names:z.write(p/"solution"/name,"solution/"+name)
        for path in sorted((p/"official"/"code").glob("*.py")):
            z.write(path,"official/code/"+path.name)
        z.write(p/"official"/"data"/"config.txt","config.txt")
        z.write(p/"q2_cold"/"frozen_manifest.json","frozen_manifest.json")
        z.writestr("README.md",
            "# 问题二独立求解代码包\n\nPython 3.12 已验证，求解仅依赖标准库。"
            "本包不含预先求出的方案、成绩表或用例答案。输入图由使用者提供。\n\n"
            "运行：`python solution/q2_submit.py graph.json -n 5 --config config.txt -o graph_multicore_res.json`。\n\n"
            "输出 JSON 只含 node_to_subgraph 与 core_schedules；旁边的 *_search 目录保存诊断。"
            "每次调用重新开始，最多 24 次原版评估，180 秒为搜索软预算，并非硬进程时限。"
            "可用核数 2～5；1 核基准按题意单独计算。\n\n"
            "独立复核：`python official/code/multicore_cut_evaluate_problem_2.py graph.json graph_multicore_res.json --config config.txt`。"
            "official/code 与 config.txt 均保留题给原版。\n")
    with tempfile.TemporaryDirectory(prefix="huawei_submission_verify_") as tmp:
        root=Path(tmp)
        with zipfile.ZipFile(archive) as z:z.extractall(root)
        shutil.copy2(p/"official"/"data"/"case_044.json",root/"unrelated_filename.json")
        command=[sys.executable,"-X","utf8",str(root/"solution"/"q2_submit.py"),
                 str(root/"unrelated_filename.json"),"-n","5","--config",str(root/"config.txt"),
                 "-o",str(root/"answer.json"),"--trace-dir",str(root/"trace")]
        subprocess.run(command,check=True,cwd=root,capture_output=True,text=True,encoding="utf-8")
        plan=json.loads((root/"answer.json").read_text())
        reference=json.loads((p/"q2_cold"/"pilot_final"/"case_044"/"n5"/"case_044_multicore_res.json").read_text())
        assert plan == reference, "isolated package differs from frozen-code pilot"
        run=json.loads((root/"trace"/"run.json").read_text())
        assert run["cold_start"] and set(plan)=={"node_to_subgraph","core_schedules"}
    audit={"archive_sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
           "archive_bytes":archive.stat().st_size,"isolated_renamed_real_input":True,
           "matches_frozen_pilot":True,"historical_result_files_in_archive":False,
           "real_case":"case_044","makespan_cycles":run["makespan_cycles"]}
    (archive.parent/"package_verification.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(audit))


if __name__=="__main__":main()
