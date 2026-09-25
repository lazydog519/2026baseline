"""Make and isolation-test the independent Q3 code-only submission bundle."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", default=["case_001", "case_044"])
    parser.add_argument("--cores", type=int, default=5)
    args = parser.parse_args()
    project, reference = args.project.resolve(), args.reference.resolve()
    dest = project / "q3_cold" / "submission_q3.zip"
    selected = [
        "solution/baseline.py", "solution/q1_optimized.py",
        "solution/q3_cold.py", "solution/q3_cold_config.json",
        "solution/q3_fusion_submit.py", "solution/q3_fusion_config.json",
        "q3_design/q3_pilot_solver.py", "q3_nsga/solve.py",
        "q3_fusion/solve.py", "q3_fusion/branch_solver.py",
        "q3_fusion/branch_experiment.json", "official/data/config.txt",
    ]
    selected += [str(p.relative_to(project)).replace("\\", "/")
                 for p in sorted((project / "official" / "code").glob("*.py"))]
    readme = (
        "# 第三问独立冷启动提交代码\n\n"
        "每次运行只读当前图、原始 config.txt 和固定算法参数；输出方案仅含 "
        "node_to_subgraph 与 core_schedules。原始图、评测器、缓存规则均未更改。\n\n"
        "环境：Python 3.12；安装 requirements.txt。原版事件评测为 CPU 程序。\n\n"
        "运行：`python solution/q3_fusion_submit.py 输入图.json -n 5 "
        "--config official/data/config.txt -o 输出方案.json`\n\n"
        "n 可取 1～5。每例重新构造候选；条件触发的 U-NSGA-III 也从当前图独立初始化。\n"
    )
    requirements = "numpy==2.5.3\npymoo==0.6.1.6\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for rel in selected:
            bundle.write(project / rel, rel)
        bundle.writestr("README.md", readme)
        bundle.writestr("requirements.txt", requirements)
    with tempfile.TemporaryDirectory(prefix="q3-isolation-", dir=dest.parent) as dirname:
        isolated = Path(dirname).resolve()
        assert isolated.is_relative_to(project)  # Temporary recursive cleanup stays in workspace.
        with zipfile.ZipFile(dest) as bundle:
            bundle.extractall(isolated)
        checks = []
        for case in args.cases:
            folder = isolated / "test" / case
            folder.mkdir(parents=True, exist_ok=True)
            graph = folder / "renamed_input.json"
            shutil.copy2(project / "official" / "data" / f"{case}.json", graph)
            output = folder / "new_plan.json"
            cmd = [sys.executable, "-X", "utf8",
                   str(isolated / "solution" / "q3_fusion_submit.py"),
                   str(graph), "-n", str(args.cores), "--config",
                   str(isolated / "official" / "data" / "config.txt"),
                   "--output", str(output), "--trace-dir", str(folder / "trace")]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(f"isolated {case}: {result.stderr[-2000:]}")
            original = reference / case / f"n{args.cores}"
            old_plan = original / "plan.json"
            old_run = json.loads((original / "run.json").read_text(encoding="utf-8"))
            new_run = json.loads((folder / "trace" / "run.json").read_text(encoding="utf-8"))
            assert json.loads(output.read_text(encoding="utf-8")) == json.loads(
                old_plan.read_text(encoding="utf-8"))
            assert new_run["final_cycles"] == old_run["final_cycles"]
            checks.append(dict(case=case, cores=args.cores,
                               reproduced_cycles=new_run["final_cycles"],
                               identical_plan=True, renamed_input=True))
    manifest = dict(schema="q3-isolated-package-v1", zip_file=dest.name,
                    zip_sha256=sha(dest), files={rel: sha(project / rel) for rel in selected},
                    isolation_checks=checks)
    (dest.parent / "package_verification.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(zip_sha256=manifest["zip_sha256"], checks=checks)), flush=True)


if __name__ == "__main__":
    main()
