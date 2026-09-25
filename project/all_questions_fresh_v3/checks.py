"""Meaningful rule counterexamples; no official evaluator import."""
import ast
from pathlib import Path
from solver import Graph, read_hardware
from mechanism import fifo_trace
from stage_candidates import stage_plan


def example(count, edges):
    ops = [{'id': i, 'op': 'ADD', 'pipe': 'PIPE_M' if i % 2 else 'PIPE_V', 'cycles': 10} for i in range(count)]
    tensors = [{'id': 100 + i, 'pos': 'UB', 'size': 8} for i in range(count)]
    links = [{'source': i, 'target': 100 + i} for i in range(count)]
    links += [{'source': 100 + a, 'target': b} for a, b in edges]
    return {'ops': ops, 'tensors': tensors, 'edges': links}


def run(cfg):
    checked = 0
    for raw in (example(1, []), example(5, []), example(4, [(0, 1), (0, 2), (1, 3), (2, 3)])):
        g = Graph(raw)
        for q in (1, 2, 3):
            for n in (1, 2, 5):
                for row in g.candidates(n, cfg, q):
                    g.validate(row['plan'], n)
                    assert all(v >= 0 for v in row['features'])
                    checked += 1
    g = Graph(example(2, [(0, 1)]))
    split = {'node_to_subgraph': {'0': 0, '1': 1}, 'core_schedules': [[0, 1]]}
    a, da = g.features(split, cfg, 1); b, db = g.features(split, cfg, 2)
    assert da['no_hit_copy_bytes'] == 24 and db['no_hit_copy_bytes'] == 8
    assert a[0] >= 120 and b[0] == 20
    fanout = Graph(example(3, [(0, 1), (0, 2)]))
    plan = {'node_to_subgraph': {'0': 0, '1': 1, '2': 2}, 'core_schedules': [[0], [1], [2]]}
    _, da = fanout.features(plan, cfg, 1); _, db = fanout.features(plan, cfg, 2)
    assert da['no_hit_copy_bytes'] == 40 and db['no_hit_copy_bytes'] == 48
    bad = Graph(example(3, [(0, 1), (1, 2)]))
    try:
        bad.validate({'node_to_subgraph': {'0': 0, '1': 1, '2': 0}, 'core_schedules': [[0], [1]]}, 2)
    except ValueError:
        pass
    else:
        raise AssertionError('cyclic contraction accepted')
    alternating = Graph(example(4, [(0, 1), (1, 2), (2, 3)]))
    serial = {'node_to_subgraph': {str(i):i for i in range(4)}, 'core_schedules': [[0, 2], [1, 3]]}
    alternating.validate(serial, 2)  # 0->1->0->1 cores; legal subgraph order.
    for name in ('depth_band','mask_band','valley_stage'):
        plan = stage_plan(alternating,2,name)
        if plan is not None: alternating.validate(plan,2)
    equal = fifo_trace([(0, i, 600, True) for i in range(4)], 10000, 60, 250)
    assert equal['trace_end'] == 40 and equal['hits'] == 0
    duplicate = fifo_trace([(0, 1, 600, True), (0, 1, 600, True), (30, 1, 600, True)], 1200, 60, 250)
    assert duplicate['insertions'] == 1 and duplicate['hits'] == 1
    # A,B inserted; hit A does not refresh; C evicts A, so A misses again.
    fifo = fifo_trace([(0, 1, 600, True), (20, 2, 600, True), (40, 1, 600, True),
                       (60, 3, 600, True), (80, 1, 600, True)], 1200, 60, 250)
    assert fifo['hits'] == 1 and fifo['evictions'] == 2
    huge = fifo_trace([(0, 1, 1201, True), (100, 1, 1201, True)], 1200, 60, 250)
    assert huge['insertions'] == huge['hits'] == 0
    modules = []
    for file in ('solver.py', 'mechanism.py'):
        for node in ast.walk(ast.parse(Path(__file__).with_name(file).read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import): modules.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom): modules.append(node.module)
    assert not any(x.startswith(('multicore', 'schedule_', 'evaluation_', 'baseline', 'q1_')) for x in modules)
    return {'checked_structural_plans': checked, 'same_core_scene_distinction': True,
            'cycle_rejected': True, 'fifo_counterexamples_passed': 4,
            'four_concurrent_transfers_cycles': equal['trace_end'], 'inference_imports': sorted(set(modules))}


if __name__ == '__main__':
    print(run(read_hardware(Path(__file__).parent.parent / 'official/data/config.txt')))
