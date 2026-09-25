# Q2 Final v1

This package contains a Q2-only solver, the Q2 experiment, report, metrics, reproducible Python figure source and seven standalone quantitative figures. It reads only official Q2 input graphs/configuration and its own fixed search settings. No Q1 score table, solution plan or experiment output is loaded by the Q2 solver.

- Method and result report: `技术思路稿-问题二独立求解.md`
- Solver and Q2-local graph utilities: `solution/`
- Search config: `solution/q2_final_config.json`
- Results: `results/`
- Seven panels (each PNG and PDF): `figures/`
- Figure/report dependencies: `requirements-figures.txt`

Install plot dependencies in a virtual environment with `python3 -m pip install -r project/q2_final_v1/requirements-figures.txt`. From repository root, reproduce 100 cases × 2–5 cores with two worker processes:

```bash
python3 project/q2_final_v1/solution/run_q2_final.py
```

The run starts cold in a clean output tree. Official graph inputs and unchanged Scene-B evaluator are under `project/official/`. Solver wall time depends on host load.
