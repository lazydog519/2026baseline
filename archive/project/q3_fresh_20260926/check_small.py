"""Small counterexamples and structural checks before official data experiments."""
import ast
from pathlib import Path
from solver import Graph, read_hardware


def example(count, edges):
    ops = [{'id': i, 'op': 'ADD', 'pipe': 'PIPE_M' if i % 2 else 'PIPE_V', 'cycles': 10}
           for i in range(count)]
    tensors = [{'id': 100 + i, 'pos': 'UB', 'size': 8} for i in range(count)]
    links = [{'source': i, 'target': 100 + i} for i in range(count)]
    links += [{'source': 100 + a, 'target': b} for a, b in edges]
    return {'ops': ops, 'tensors': tensors, 'edges': links}


def main():
    cfg = read_hardware(Path(__file__).resolve().parent.parent / 'official/data/config.txt')
    checks = 0
    for raw in (example(1, []), example(5, []), example(4, [(0, 1), (0, 2), (1, 3), (2, 3)]),
                example(5, [(0, 1), (1, 2), (2, 3), (3, 4)])):
        graph = Graph(raw)
        for n in (1, 2, 5):
            for row in graph.candidates(n, cfg):
                graph.validate(row['plan'], n)
                assert all(x >= 0 for x in row['features'])
                checks += 1
    graph = Graph(example(3, [(0, 1), (1, 2)]))
    bad = {'node_to_subgraph': {'0': 0, '1': 1, '2': 0}, 'core_schedules': [[0], [1]]}
    try:
        graph.validate(bad, 2)
    except ValueError as exc:
        assert 'cycle' in str(exc)
    else:
        raise AssertionError('cyclic contraction accepted')
    tree = ast.parse(Path(__file__).with_name('solver.py').read_text(encoding='utf-8'))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module)
    assert not any(x.startswith(('multicore', 'schedule_', 'evaluation_', 'baseline', 'q1_')) for x in modules)
    # Equal-size fair-sharing transfers: cumulative completion time is NOT makespan.
    n, size, bandwidth = 4, 600, 60
    concurrent_makespan = n * size / bandwidth
    assert concurrent_makespan == n * (size / bandwidth) == 40
    assert n * concurrent_makespan == 160
    print({'structural_plans_checked': checks, 'cycle_rejected': True,
           'inference_imports': modules, 'ddr_counterexample_cycles': concurrent_makespan})


if __name__ == '__main__':
    main()
