"""Development-only official labels and post-freeze validation.

Never distributed in the inference ZIP. No historical results are read.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import numpy as np
from solver import Graph, FEATURES, VERSION, digest, read_hardware

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
OFFICIAL = PROJECT / 'official'
CONFIG = OFFICIAL / 'data' / 'config.txt'


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def official_hashes():
    return {str(p.relative_to(OFFICIAL)): digest(p) for p in OFFICIAL.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def prepare():
    profiles = []
    for source in sorted((OFFICIAL / 'data').glob('case_*.json')):
        if source.stem.count('_') != 1:
            continue
        graph = Graph(json.loads(source.read_text(encoding='utf-8')))
        profiles.append({'case': source.stem, 'sha256': digest(source), **graph.profile()})
    assert len(profiles) == 100
    with (HERE / 'input_profiles.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, list(profiles[0]))
        writer.writeheader()
        writer.writerows(profiles)
    buckets = {name: [] for name in ('vector', 'decomposable', 'entangled')}
    for r in profiles:
        if not 200 <= r['compute_ops'] <= 6500:
            continue
        key = ('vector' if r['vector_share'] > 0.5 else 'decomposable'
               if r['weak_components'] >= 5 and r['largest_component_fraction'] <= 0.5 else 'entangled')
        buckets[key].append(r)
    train, validation, selection = [], [], {}
    for name, rows in buckets.items():
        rows.sort(key=lambda r: (r['compute_ops'], r['sha256']))
        assert len(rows) >= 4
        chosen = [rows[int((len(rows) - 1) * q)]['case'] for q in (0.25, 0.5, 0.75)]
        assert len(set(chosen)) == 3
        train.extend((chosen[0], chosen[2]))
        validation.append(chosen[1])
        selection[name] = {'eligible_count': len(rows), 'train': [chosen[0], chosen[2]], 'validation': chosen[1]}
    manifest = {'round': VERSION, 'selected_before_labels': True, 'train': train,
                'validation': validation, 'cores': 5, 'selection': selection,
                'historical_scores_or_plans_read': False,
                'solver_sha256': digest(HERE / 'solver.py'), 'official_sha256': official_hashes(),
                'fit': {'type': 'nonnegative_ridge', 'lambda': 0.01, 'seed': None},
                'scope': 'small/medium development pilot; not a 100-case final score'}
    cfg = read_hardware(CONFIG)
    generated = []
    for case in train:
        source = OFFICIAL / 'data' / (case + '.json')
        graph = Graph(json.loads(source.read_text(encoding='utf-8')))
        for candidate in graph.candidates(5, cfg):
            folder = HERE / 'train' / case / candidate['name']
            write(folder / 'plan.json', candidate['plan'])
            write(folder / 'features.json', {k: v for k, v in candidate.items() if k != 'plan'})
            generated.append({'case': case, 'name': candidate['name'],
                              'plan_sha256': digest(folder / 'plan.json')})
    manifest['frozen_training_plans'] = generated
    write(HERE / 'manifest.json', manifest)
    print(json.dumps({'train': train, 'validation': validation, 'training_plans': len(generated)}), flush=True)


def evaluator_setup():
    sys.path.insert(0, str(OFFICIAL / 'code'))
    from multicore_cut_evaluate_problem_3 import evaluate_problem_3, read_cache_config
    from multicore_cut_evaluate_problem_2 import evaluate_scene_b
    from singlecore_evaluate import evaluate_singlecore
    cfg = read_hardware(CONFIG)
    params = {'capacity': cfg['capacity'], 'bandwidth': cfg['bandwidth']['bandwidth'],
              'cross_core_copy_delay': cfg['multicore_scene_b']['cross_core_copy_delay_cycles']}
    return evaluate_problem_3, evaluate_scene_b, evaluate_singlecore, params, read_cache_config(str(CONFIG))


def save_result(path, result):
    with gzip.open(path, 'wt', encoding='utf-8', compresslevel=1) as stream:
        json.dump(result, stream, separators=(',', ':'))


def label(job):
    q3, _, _, params, cache = evaluator_setup()
    folder = HERE / 'train' / job['case'] / job['name']
    assert digest(folder / 'plan.json') == job['plan_sha256']
    graph = json.loads((OFFICIAL / 'data' / (job['case'] + '.json')).read_text(encoding='utf-8'))
    start = time.perf_counter()
    try:
        result = q3(graph, json.loads((folder / 'plan.json').read_text(encoding='utf-8')), **params, **cache)
        save_result(folder / 'official_q3.json.gz', result)
        row = {**job, 'status': 'ok', 'makespan': result['makespan'], 'label_seconds': time.perf_counter() - start}
    except Exception as exc:
        row = {**job, 'status': 'failed', 'error': repr(exc)}
    write(folder / 'label.json', row)
    return row


def fit_nonnegative(x, y, penalty):
    scale = np.sqrt(np.mean(x * x, axis=0))
    scale[scale < 1e-12] = 1
    z = x / scale
    gram = z.T @ z + penalty * np.eye(z.shape[1])
    rhs = z.T @ y
    weights = np.zeros(z.shape[1])
    for _ in range(4000):
        previous = weights.copy()
        for j in range(len(weights)):
            weights[j] = max(0., weights[j] + (rhs[j] - gram[j] @ weights) / gram[j, j])
        if np.max(np.abs(weights - previous)) < 1e-10:
            break
    return weights / scale


def train(workers):
    manifest = json.loads((HERE / 'manifest.json').read_text(encoding='utf-8'))
    assert digest(HERE / 'solver.py') == manifest['solver_sha256']
    jobs = manifest['frozen_training_plans']
    with ProcessPoolExecutor(max_workers=workers) as executor:
        rows = []
        for future in as_completed([executor.submit(label, j) for j in jobs]):
            row = future.result()
            rows.append(row)
            print(row['case'], row['name'], row['status'], row.get('makespan'), flush=True)
    write(HERE / 'training_labels.json', rows)
    if any(r['status'] != 'ok' for r in rows):
        raise RuntimeError('training feasibility failures: inspect before continuing')
    rows.sort(key=lambda r: (r['case'], r['name']))
    raw_features = np.array([json.loads((HERE / 'train' / r['case'] / r['name'] / 'features.json').read_text(
        encoding='utf-8'))['features'] for r in rows], dtype=float)
    # Each graph gets its own common physical scale, never an official score scale.
    denominators = {case: max(1., min(raw_features[i, 0] for i, r in enumerate(rows) if r['case'] == case))
                    for case in manifest['train']}
    scales = np.array([denominators[r['case']] for r in rows])
    x, y = raw_features / scales[:, None], np.array([r['makespan'] for r in rows]) / scales
    weights = fit_nonnegative(x, y, manifest['fit']['lambda'])
    cv = []
    for case in manifest['train']:
        held = np.array([r['case'] == case for r in rows])
        w = fit_nonnegative(x[~held], y[~held], manifest['fit']['lambda'])
        indices = np.flatnonzero(held)
        predicted = min(indices, key=lambda i: (raw_features[i] @ w, rows[i]['name']))
        actual_best = min(rows[i]['makespan'] for i in indices)
        cv.append({'case': case, 'selected': rows[predicted]['name'],
                   'relative_regret': rows[predicted]['makespan'] / actual_best - 1})
    model = {'solver_version': VERSION, 'features': FEATURES, 'weights': weights.tolist(),
             'fit': manifest['fit'], 'origin': 'only this round fresh training labels'}
    write(HERE / 'model.json', model)
    write(HERE / 'fit_report.json', {'samples': len(rows), 'training_cases': len(manifest['train']),
           'weights': weights.tolist(), 'group_cv': cv,
           'mean_group_cv_regret': float(np.mean([r['relative_regret'] for r in cv])),
           'in_sample_relative_error_mean': float(np.mean(np.abs(raw_features @ weights /
                                         np.array([r['makespan'] for r in rows]) - 1))),
           'model_sha256': digest(HERE / 'model.json')})
    print('MODEL_FROZEN', digest(HERE / 'model.json'), flush=True)


def validate_case(case):
    q3, q2, single, params, cache = evaluator_setup()
    graph = json.loads((OFFICIAL / 'data' / (case + '.json')).read_text(encoding='utf-8'))
    reference = single(graph, bandwidth=params['bandwidth'], capacity=params['capacity'])['makespan']
    results, rows = {}, []
    for method in ('component_scalar', 'trained'):
        folder = HERE / 'validation' / case / method
        plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
        generation = json.loads((folder / 'generation.json').read_text(encoding='utf-8'))
        assert digest(folder / 'plan.json') == generation['plan_sha256']
        fingerprint = json.dumps(plan, sort_keys=True)
        if fingerprint not in results:
            l2, no_l2 = q3(graph, plan, **params, **cache), q2(graph, plan, **params)
            results[fingerprint] = l2, no_l2
        l2, no_l2 = results[fingerprint]
        save_result(folder / 'official_l2.json.gz', l2)
        save_result(folder / 'official_no_l2.json.gz', no_l2)
        rows.append({'case': case, 'method': method, 'selected': generation['selected'],
            'makespan': l2['makespan'], 'same_plan_no_l2': no_l2['makespan'],
            'l2_gain': no_l2['makespan'] / l2['makespan'],
            'speedup_vs_original_singlecore': reference / l2['makespan'],
            'cache_byte_hit_rate': l2['cache_stats']['hit_rate'],
            'added_copy_bytes': l2['data_movement_bytes']['added_copy_bytes'],
            'generation_seconds': generation['generation_seconds'], 'official_generation_calls': 0,
            'plan_sha256': generation['plan_sha256']})
    return rows, 2 * len(results) + 1


def validate(workers):
    manifest = json.loads((HERE / 'manifest.json').read_text(encoding='utf-8'))
    assert digest(HERE / 'solver.py') == manifest['solver_sha256']
    assert official_hashes() == manifest['official_sha256']
    model_hash = digest(HERE / 'model.json')
    generations = []
    # All final plans are generated and frozen BEFORE any held-out official run.
    with tempfile.TemporaryDirectory(prefix='q3_fresh_isolated_') as temporary:
        root = Path(temporary)
        shutil.copy2(HERE / 'solver.py', root / 'solver.py')
        shutil.copy2(HERE / 'model.json', root / 'model.json')
        shutil.copy2(CONFIG, root / 'config.txt')
        for i, case in enumerate(manifest['validation']):
            shutil.copy2(OFFICIAL / 'data' / (case + '.json'), root / 'unknown_graph.json')
            for method in ('component_scalar', 'trained'):
                folder = HERE / 'validation' / case / method
                folder.mkdir(parents=True, exist_ok=True)
                cmd = [sys.executable, '-I', str(root / 'solver.py'), str(root / 'unknown_graph.json'),
                       '-n', '5', '--config', str(root / 'config.txt'), '--model', str(root / 'model.json'),
                       '--method', method, '-o', str(root / 'plan.json'), '--report', str(root / 'generation.json')]
                subprocess.run(cmd, cwd=root, check=True, capture_output=True, timeout=60)
                shutil.copy2(root / 'plan.json', folder / 'plan.json')
                shutil.copy2(root / 'generation.json', folder / 'generation.json')
                expected = digest(root / 'plan.json')
                # Same unseen input, fresh process, no previous plan present.
                (root / 'plan.json').unlink()
                subprocess.run(cmd, cwd=root, check=True, capture_output=True, timeout=60)
                assert digest(root / 'plan.json') == expected
                generations.append({'case': case, 'method': method, 'plan_sha256': expected,
                                    'renamed_input': True, 'fresh_process_repeat_match': True})
    write(HERE / 'validation_generation_freeze.json', {'model_sha256': model_hash,
          'solver_sha256': digest(HERE / 'solver.py'), 'plans': generations,
          'official_evaluation_started_after_all_plans_frozen': True})
    rows, calls = [], 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for future in as_completed([executor.submit(validate_case, c) for c in manifest['validation']]):
            got, count = future.result()
            rows.extend(got)
            calls += count
            print('VALIDATED', got[0]['case'], [(r['method'], r['makespan']) for r in got], flush=True)
    assert digest(HERE / 'model.json') == model_hash
    assert official_hashes() == manifest['official_sha256']
    write(HERE / 'validation_results.json', sorted(rows, key=lambda r: (r['case'], r['method'])))
    metrics = {}
    for method in ('component_scalar', 'trained'):
        subset = [r for r in rows if r['method'] == method]
        metrics[method] = {key: float(np.mean([r[key] for r in subset])) for key in
            ('l2_gain', 'speedup_vs_original_singlecore', 'cache_byte_hit_rate', 'generation_seconds')}
    paired = []
    for case in manifest['validation']:
        a, b = [next(r for r in rows if r['case'] == case and r['method'] == m)
                for m in ('component_scalar', 'trained')]
        paired.append({'case': case, 'relative_makespan_reduction': 1 - b['makespan'] / a['makespan']})
    write(HERE / 'summary.json', {'scope': '3 held-out medium/small cases, 5 cores, not full contest score',
         'training_cases': manifest['train'], 'held_out_cases': manifest['validation'],
         'metrics': metrics, 'paired': paired, 'validation_official_calls': calls,
         'official_calls_during_final_generation': 0, 'official_files_unchanged': len(official_hashes()),
         'model_and_solver_frozen': True, 'isolation_renaming_repeat_tests': len(generations)})
    with zipfile.ZipFile(HERE / 'submission_prototype.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('solver.py', 'model.json'):
            archive.write(HERE / name, name)
    print(json.dumps(metrics), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('phase', choices=['prepare', 'train', 'validate'])
    ap.add_argument('--workers', type=int, default=2)
    args = ap.parse_args()
    {'prepare': prepare, 'train': lambda: train(args.workers), 'validate': lambda: validate(args.workers)}[args.phase]()
