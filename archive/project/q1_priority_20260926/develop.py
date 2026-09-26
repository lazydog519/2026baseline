"""Development-only official labels; never import this file from solver.py."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from solver import candidates

DEVELOPMENT = (10, 18, 23, 37, 61, 70, 78, 96)
HOLDOUT = (6, 15, 19, 94)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('phase', choices=('generate', 'evaluate'))
    ap.add_argument('--scope', choices=('development', 'holdout'), required=True)
    ap.add_argument('--cores', type=int, nargs='+', default=[5])
    ap.add_argument('--project', type=Path, required=True)
    a = ap.parse_args()
    project = a.project.resolve()
    root = Path(__file__).resolve().parent / a.scope
    root.mkdir(parents=True, exist_ok=True)
    cases = DEVELOPMENT if a.scope == 'development' else HOLDOUT
    if a.phase == 'generate':
        for i in cases:
            name = f'case_{i:03d}'
            graph_path = project / 'official/data' / f'{name}.json'
            graph = json.loads(graph_path.read_text(encoding='utf-8'))
            for n in a.cores:
                rows, rejected = candidates(graph, n)
                path = root / f'{name}_n{n}.json'
                if path.exists():
                    raise FileExistsError(f'candidate set already frozen: {path}')
                path.write_text(json.dumps(dict(case=name, cores=n, input_sha256=digest(graph_path),
                                                candidates=rows, rejected=rejected),
                                           separators=(',', ':'))+'\n', encoding='utf-8')
                print(name, n, len(rows), len(rejected), digest(path), flush=True)
    else:
        sys.path.insert(0, str(project / 'official/code'))
        from evaluation_validation import read_evaluation_config
        from multicore_cut_evaluate_problem_1 import evaluate_scene_a, read_scene_a_config
        cfg = read_evaluation_config(str(project / 'official/data/config.txt'))
        scene = read_scene_a_config(str(project / 'official/data/config.txt'))
        kwargs = dict(bandwidth=cfg['bandwidth'], capacity=cfg['capacity'],
                      same_core_wait=scene['task_same_core_wait_cycles'],
                      cross_core_wait=scene['task_cross_core_wait_cycles'])
        output = root / 'labels.jsonl'
        if output.exists():
            raise FileExistsError(f'labels already exist: {output}')
        with output.open('w', encoding='utf-8') as stream:
            for i in cases:
                name = f'case_{i:03d}'
                graph_path = project / 'official/data' / f'{name}.json'
                graph = json.loads(graph_path.read_text(encoding='utf-8'))
                for n in a.cores:
                    frozen = root / f'{name}_n{n}.json'
                    record = json.loads(frozen.read_text(encoding='utf-8'))
                    assert record['input_sha256'] == digest(graph_path)
                    for candidate in record['candidates']:
                        start = time.perf_counter()
                        label = dict(case=name, cores=n, candidate=candidate['name'],
                                     candidate_sha256=candidate['fingerprint'],
                                     frozen_sha256=digest(frozen), proxy_cycles=candidate['proxy_cycles'],
                                     boundary_bytes=candidate['boundary_bytes'], tasks=candidate['tasks'])
                        try:
                            result = evaluate_scene_a(graph, candidate['plan'], **kwargs)
                            label.update(status='ok', cycles=result['makespan'],
                                         added_copy_bytes=result['data_movement_bytes']['added_copy_bytes'])
                        except (ValueError, RuntimeError) as exc:
                            label.update(status='error', error=str(exc))
                        label['seconds'] = time.perf_counter()-start
                        stream.write(json.dumps(label, separators=(',', ':'))+'\n')
                        stream.flush()
                        print(name, n, candidate['name'], label['status'], label.get('cycles'),
                              round(label['seconds'], 2), flush=True)


if __name__ == '__main__':
    main()
