"""Cold per-input pilot inference; official evaluator and labels are absent."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from graph_primitives import Graph, read_hardware
from candidate_family import shortlist
from selection_policy import choose


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(graph_path, config_path, model_path, n, q):
    if n not in range(1, 6) or q not in (1, 2, 3):
        raise ValueError('cores must be 1..5 and question must be 1, 2 or 3')
    if n == 1 and q in (1, 2):
        raise ValueError('questions 1/2 use the official whole-graph single-core baseline; no cut search')
    model = json.loads(Path(model_path).read_text(encoding='utf-8'))
    if digest(config_path) != model['hardware_sha256']:
        raise ValueError('hardware config differs from the frozen development setting')
    raw = json.loads(Path(graph_path).read_text(encoding='utf-8'))
    g = Graph(raw)
    if n == 1:
        plan = {'node_to_subgraph': {str(v): 0 for v in g.ops}, 'core_schedules': [[0]]}
        g.validate(plan, n)
        selected = {'name': 'canonical_single_core', 'plan': plan}
        return selected, {'question': q, 'cores': n, 'candidate_count': 1,
                          'rejected_moves': [], 'selected': selected['name'],
                          'official_calls': 0, 'graph_sha256': digest(graph_path),
                          'config_sha256': digest(config_path), 'model_sha256': digest(model_path)}
    candidates, failures = shortlist(g, n, read_hardware(config_path), q)
    idx = 0 if n == 1 else choose([{**row, 'cores': n} for row in candidates],
                                  model['coefficients'][str(q)], model['margin'])[0]
    selected = candidates[idx]
    g.validate(selected['plan'], n)
    return selected, {'question': q, 'cores': n, 'candidate_count': len(candidates),
                      'rejected_moves': failures, 'selected': selected['name'],
                      'official_calls': 0, 'graph_sha256': digest(graph_path),
                      'config_sha256': digest(config_path), 'model_sha256': digest(model_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('graph', type=Path)
    ap.add_argument('-n', '--cores', type=int, required=True)
    ap.add_argument('--question', type=int, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--model', type=Path, default=Path(__file__).with_name('model.json'))
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--report', type=Path)
    args = ap.parse_args()
    started = time.perf_counter()
    selected, report = run(args.graph, args.config, args.model, args.cores, args.question)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selected['plan'], sort_keys=True), encoding='utf-8')
    report['plan_sha256'] = digest(args.output)
    report['generation_seconds'] = time.perf_counter() - started
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'selected': report['selected'], 'official_calls': 0,
                      'generation_seconds': report['generation_seconds']}))


if __name__ == '__main__':
    main()
