"""Cheap structural checks across all official inputs; NOT official scoring."""
import json
from pathlib import Path
import time
from solver_v2 import Graph, digest, read_hardware

root = Path(__file__).resolve().parent
official = root.parent / 'official'
cfg = read_hardware(official / 'data/config.txt')
start = time.perf_counter()
rows = []
for source in sorted((official / 'data').glob('case_*.json')):
    if source.stem.count('_') != 1:
        continue
    graph = Graph(json.loads(source.read_text(encoding='utf-8')))
    for n in range(1, 6):
        for mode in ('component_scalar', 'component_vector', 'join_tail', 'shared_prefix'):
            graph.validate(graph.build(n, mode), n)
    rows.append({'case': source.stem, 'input_sha256': digest(source), 'plans_checked': 20})
    if len(rows) % 20 == 0:
        print('checked', len(rows), flush=True)
assert len(rows) == 100
result = {'official_calls': 0, 'cases': 100, 'cores': [1, 2, 3, 4, 5],
          'construction_checks': 2000, 'scope': 'coverage, SG/core ordering DAG only; not official execution',
          'elapsed_seconds': time.perf_counter() - start,
          'solver_sha256': digest(root / 'solver_v2.py'), 'rows': rows}
(root / 'v2/structural_screen.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in result.items() if k != 'rows'}), flush=True)
