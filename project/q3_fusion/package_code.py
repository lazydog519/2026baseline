"""Build and isolation-test a ZIP with no historical plans or case inputs."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = HERE.parent
FILES = [
    HERE / "submit.py", HERE / "branch_solver.py", HERE / "solve.py",
    HERE / "branch_experiment.json", P / "q3_nsga/solve.py",
    P / "q3_design/q3_pilot_solver.py", P / "solution/baseline.py",
    P / "solution/q1_optimized.py", P / "official/data/config.txt",
]
FILES += sorted((P / "official/code").glob("*.py"))


def main():
    output = HERE / "q3_branch_code_only.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in FILES:
            z.write(path, "project/" + path.relative_to(P).as_posix())
        z.writestr("project/README.txt",
                   "Python with numpy and pymoo==0.6.1.6 required.\n"
                   "Run q3_fusion/submit.py official/data/<graph>.json -n 5.\n"
                   "The graph and config.txt must be in the same directory.\n"
                   "The output plan contains only node_to_subgraph and core_schedules.\n")
    with tempfile.TemporaryDirectory(prefix="q3_isolated_") as temp:
        isolated = Path(temp)
        with zipfile.ZipFile(output) as z:
            z.extractall(isolated)
        root = isolated / "project"
        renamed = root / "official/data/independent_renamed_input.json"
        shutil.copyfile(P / "official/data/case_069.json", renamed)
        result = isolated / "plan.json"
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(root / "q3_fusion/submit.py"),
             str(renamed), "-n", "5", "--seed", "17",
             "--output", str(result)],
            capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(proc.stderr[-4000:] or proc.stdout[-4000:])
        reproduced = json.loads(result.read_text(encoding="utf-8"))
        expected = json.loads((HERE /
            "branch_validation/case_069/branch/seed_17/plan.json").read_text(
                encoding="utf-8"))
        assert reproduced == expected
        assert set(reproduced) == {"node_to_subgraph", "core_schedules"}
    manifest = dict(package_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                    files=[{"path": path.relative_to(P).as_posix(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                           for path in FILES],
                    historical_plans_included=False, case_inputs_included=False,
                    renamed_input_isolated_reproduction=True,
                    reference_case="case_069", cores=5, seed=17)
    (HERE / "code_package_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in (
        "package_sha256", "renamed_input_isolated_reproduction",
        "historical_plans_included", "case_inputs_included")}))


if __name__ == "__main__":
    main()
