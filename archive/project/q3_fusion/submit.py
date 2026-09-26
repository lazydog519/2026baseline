"""Code-only Problem 3 entry point: graph JSON + core count -> official plan."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path)
    ap.add_argument("-n", "--cores", type=int, choices=range(1, 6), required=True)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    graph = args.graph.resolve()
    dest = (args.output.resolve() if args.output else
            graph.with_name(graph.stem + "_multicore_res.json"))
    if not (graph.parent / "config.txt").exists():
        ap.error("原附件 config.txt 必须与计算图在同一目录")
    with tempfile.TemporaryDirectory(prefix="q3_search_") as temp:
        tmp = Path(temp)
        command = [sys.executable, "-X", "utf8", str(HERE / "branch_solver.py"),
                   str(graph), "-n", str(args.cores), "--seed", str(args.seed),
                   "--output", str(tmp), "--parameters",
                   str(HERE / "branch_experiment.json")]
        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode:
            raise SystemExit(proc.stderr[-3000:] or proc.stdout[-3000:])
        plan = json.loads((tmp / "plan.json").read_text(encoding="utf-8"))
    assert set(plan) == {"node_to_subgraph", "core_schedules"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(plan, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    print(str(dest))


if __name__ == "__main__":
    main()
