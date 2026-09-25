"""One first-principles correction; new held-out cases, same fresh training labels."""
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
import numpy as np
import csv
from solver_v2 import Graph, VERSION, FEATURES, read_hardware, digest
from experiment import fit_nonnegative, evaluator_setup, write, save_result, official_hashes

HERE = Path(__file__).resolve().parent
OUT = HERE / 'v2'
OFFICIAL = HERE.parent / 'official'
CONFIG = OFFICIAL / 'data/config.txt'


def audit_case(case):
    q3, q2, single, params, cache = evaluator_setup()
    graph = json.loads((OFFICIAL / 'data' / (case + '.json')).read_text(encoding='utf-8'))
    reference = single(graph, bandwidth=params['bandwidth'], capacity=params['capacity'])['makespan']
    cache_result, rows = {}, []
    for method in ('component_scalar', 'trained'):
        folder = OUT / 'validation' / case / method
        plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
        meta = json.loads((folder / 'generation.json').read_text(encoding='utf-8'))
        assert digest(folder / 'plan.json') == meta['plan_sha256']
        signature = json.dumps(plan, sort_keys=True)
        if signature not in cache_result:
            cache_result[signature] = q3(graph, plan, **params, **cache), q2(graph, plan, **params)
        l2, no_l2 = cache_result[signature]
        save_result(folder / 'official_l2.json.gz', l2)
        save_result(folder / 'official_no_l2.json.gz', no_l2)
        feature, detail = Graph(graph).features(plan, read_hardware(CONFIG))
        assert feature[0] <= l2['makespan'] + 1e-6, (case, method, feature[0], l2['makespan'])
        rows.append({'case': case, 'method': method, 'selected': meta['selected'],
           'makespan': l2['makespan'], 'same_plan_no_l2': no_l2['makespan'],
           'l2_gain': no_l2['makespan'] / l2['makespan'],
           'speedup_vs_original_singlecore': reference / l2['makespan'],
           'cache_byte_hit_rate': l2['cache_stats']['hit_rate'],
           'added_copy_bytes': l2['data_movement_bytes']['added_copy_bytes'],
           'generation_seconds': meta['generation_seconds'], 'official_generation_calls': 0,
           'physical_lower_bound': feature[0], 'plan_sha256': meta['plan_sha256']})
    return rows, 2 * len(cache_result) + 1


def main():
    OUT.mkdir(exist_ok=True)
    old_manifest = json.loads((HERE / 'manifest.json').read_text(encoding='utf-8'))
    assert official_hashes() == old_manifest['official_sha256']
    cfg = read_hardware(CONFIG)
    rows = sorted(json.loads((HERE / 'training_labels.json').read_text(encoding='utf-8')),
                  key=lambda r: (r['case'], r['name']))
    features = []
    for row in rows:
        folder = HERE / 'train' / row['case'] / row['name']
        assert digest(folder / 'plan.json') == row['plan_sha256']
        raw = json.loads((OFFICIAL / 'data' / (row['case'] + '.json')).read_text(encoding='utf-8'))
        feature, detail = Graph(raw).features(json.loads((folder / 'plan.json').read_text(encoding='utf-8')), cfg)
        assert feature[0] <= row['makespan'] + 1e-6
        features.append(feature)
    features = np.array(features)
    scales = {c: min(features[i, 0] for i, r in enumerate(rows) if r['case'] == c)
              for c in old_manifest['train']}
    scale = np.array([max(1, scales[r['case']]) for r in rows])
    x, y = features / scale[:, None], np.array([r['makespan'] for r in rows]) / scale
    weights = fit_nonnegative(x, y, 0.01)
    write(OUT / 'model.json', {'solver_version': VERSION, 'features': FEATURES,
          'weights': weights.tolist(), 'fit': {'type': 'nonnegative_ridge', 'lambda': 0.01, 'seed': None},
          'origin': '17 fresh labels from this round only; physical prediction floor enforced'})
    profiles = list(csv.DictReader((HERE / 'input_profiles.csv').open(encoding='utf-8')))
    excluded = set(old_manifest['train'] + old_manifest['validation'])
    buckets = {k: [] for k in ('vector', 'decomposable', 'entangled')}
    for r in profiles:
        if r['case'] in excluded or not 200 <= int(r['compute_ops']) <= 6500:
            continue
        key = ('vector' if float(r['vector_share']) > 0.5 else 'decomposable'
               if int(r['weak_components']) >= 5 and float(r['largest_component_fraction']) <= 0.5 else 'entangled')
        buckets[key].append(r)
    selected = {k: min(v, key=lambda r: hashlib.sha256(('fresh-v2-test:' + r['sha256']).encode()).hexdigest())['case']
                for k, v in buckets.items()}
    manifest = {'round': VERSION, 'train': old_manifest['train'], 'held_out': selected,
         'excluded_previous_diagnostic_cases': old_manifest['validation'],
         'training_label_sha256': digest(HERE / 'training_labels.json'),
         'training_labels_recomputed_this_round': True, 'prior_project_results_read': False,
         'model_sha256': digest(OUT / 'model.json'), 'solver_sha256': digest(HERE / 'solver_v2.py'),
         'official_sha256': official_hashes(), 'selection_before_any_v2_holdout_labels': True}
    write(OUT / 'manifest.json', manifest)
    print('NEW_HELD_OUT', selected, flush=True)
    generations = []
    with tempfile.TemporaryDirectory(prefix='fresh_q3_v2_') as temporary:
        root = Path(temporary)
        for source, name in ((HERE / 'solver_v2.py', 'solver.py'), (OUT / 'model.json', 'model.json'), (CONFIG, 'config.txt')):
            shutil.copy2(source, root / name)
        for case in selected.values():
            shutil.copy2(OFFICIAL / 'data' / (case + '.json'), root / 'unseen_input.json')
            for method in ('component_scalar', 'trained'):
                folder = OUT / 'validation' / case / method
                folder.mkdir(parents=True, exist_ok=True)
                command = [sys.executable, '-I', str(root / 'solver.py'), str(root / 'unseen_input.json'),
                    '-n', '5', '--config', str(root / 'config.txt'), '--model', str(root / 'model.json'),
                    '--method', method, '-o', str(root / 'plan.json'), '--report', str(root / 'generation.json')]
                subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=60)
                shutil.copy2(root / 'plan.json', folder / 'plan.json')
                shutil.copy2(root / 'generation.json', folder / 'generation.json')
                expected = digest(root / 'plan.json')
                (root / 'plan.json').unlink()
                subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=60)
                assert expected == digest(root / 'plan.json')
                generations.append({'case': case, 'method': method, 'plan_sha256': expected,
                                    'isolated_renamed_fresh_process_repeat': True})
    write(OUT / 'generation_freeze.json', {'model_sha256': manifest['model_sha256'], 'plans': generations,
                                         'all_generated_before_official_holdout_evaluation': True})
    results, calls = [], 0
    with ProcessPoolExecutor(max_workers=2) as executor:
        for future in as_completed([executor.submit(audit_case, c) for c in selected.values()]):
            got, count = future.result()
            results.extend(got)
            calls += count
            print('AUDITED', [(r['case'], r['method'], r['makespan']) for r in got], flush=True)
    write(OUT / 'validation_results.json', sorted(results, key=lambda r: (r['case'], r['method'])))
    metrics = {}
    for method in ('component_scalar', 'trained'):
        subset = [r for r in results if r['method'] == method]
        metrics[method] = {k: float(np.mean([r[k] for r in subset])) for k in
                         ('l2_gain', 'speedup_vs_original_singlecore', 'cache_byte_hit_rate', 'generation_seconds')}
    paired = []
    for case in selected.values():
        a, b = [next(r for r in results if r['case'] == case and r['method'] == m)
                for m in ('component_scalar', 'trained')]
        paired.append({'case': case, 'relative_makespan_reduction': 1 - b['makespan'] / a['makespan']})
    assert digest(OUT / 'model.json') == manifest['model_sha256']
    assert digest(HERE / 'solver_v2.py') == manifest['solver_sha256']
    assert official_hashes() == manifest['official_sha256']
    summary = {'scope': '3 new held-out cases, 5 cores; not the 100-case mean',
        'metrics': metrics, 'paired': paired, 'validation_official_calls': calls,
        'official_calls_during_generation': 0, 'isolated_repeat_count': len(generations),
        'official_files_unchanged': len(official_hashes()), 'model_and_solver_frozen': True,
        'all_observed_physical_lower_bounds_valid': True}
    write(OUT / 'summary.json', summary)
    with zipfile.ZipFile(OUT / 'submission_prototype.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(HERE / 'solver_v2.py', 'solver.py')
        archive.write(OUT / 'model.json', 'model.json')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
