"""Development/acceptance only. Deliberately excluded from inference package."""
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
from checks import run as small_checks

HERE = Path(__file__).resolve().parent
OFFICIAL = HERE.parent / 'official'
CONFIG = OFFICIAL / 'data/config.txt'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def hashes():
    return {p.relative_to(OFFICIAL).as_posix(): digest(p) for p in OFFICIAL.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def source_hashes():
    return {f: digest(HERE / f) for f in ('solver.py', 'mechanism.py')}


def preflight():
    manifest = json.loads((HERE / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['official_sha256'] == hashes(), 'official rules/files changed'
    assert manifest['solver_sha256'] == source_hashes(), 'solver changed: create new version before rerunning'
    assert read_hardware(CONFIG) == manifest['hardware']
    print('PREFLIGHT: A=Task/100/1000; B=core/500; L1=524288 UB=131072; DDR=60; FIFO=1048576/250; inference official calls=0', flush=True)
    return manifest


def read_graph(case):
    return json.loads((OFFICIAL / 'data' / (case + '.json')).read_text(encoding='utf-8'))


def prepare():
    if (HERE / 'generation_freeze.json').exists():
        raise RuntimeError('frozen evidence exists: copy source scripts to a new empty experiment directory')
    cfg = read_hardware(CONFIG)
    write(HERE / 'small_checks.json', small_checks(cfg))
    profiles = []
    for p in sorted((OFFICIAL / 'data').glob('case_*.json')):
        if p.stem.count('_') != 1: continue
        g = Graph(json.loads(p.read_text(encoding='utf-8')))
        profiles.append({'case': p.stem, 'sha256': digest(p), **g.profile()})
    assert len(profiles) == 100
    with (HERE / 'input_profiles.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, list(profiles[0])); w.writeheader(); w.writerows(profiles)
    # Reuse the current round's pre-score structural training selection, NOT its weights/results.
    train = ['case_029', 'case_040', 'case_046', 'case_007', 'case_048', 'case_082']
    earlier_diagnostics = ['case_055', 'case_013', 'case_088', 'case_024', 'case_083', 'case_069']
    validation, strata = [], {}
    for r in profiles:
        if not 200 <= r['compute_ops'] <= 6500 or r['case'] in train + earlier_diagnostics: continue
        kind = 'vector' if r['vector_share'] > .5 else 'decomposable' if r['weak_components'] >= 5 and r['largest_component_fraction'] <= .5 else 'entangled'
        strata.setdefault(kind, []).append(r)
    for kind, rows in strata.items():
        rows.sort(key=lambda r: r['sha256'])
        validation.extend(r['case'] for r in rows[:2])
    jobs = []
    for case in train:
        g = Graph(read_graph(case))
        for q in (1, 2, 3):
            for n in (2, 5):
                for row in g.candidates(n, cfg, q):
                    path = Path('train') / case / f'q{q}_n{n}' / row['name']
                    write(HERE / path / 'plan.json', row['plan'])
                    write(HERE / path / 'features.json', {k: v for k, v in row.items() if k != 'plan'})
                    jobs.append({'case': case, 'question': q, 'cores': n, 'name': row['name'],
                                 'path': path.as_posix(), 'plan_sha256': digest(HERE / path / 'plan.json')})
    manifest = dict(version=VERSION, train=train, validation=validation, earlier_diagnostic_cases=earlier_diagnostics,
        train_cores=[2, 5], validation_cores=[1, 2, 3, 4, 5], questions=[1, 2, 3],
        scope='six small/medium held-out graphs, not full official 100-case scores',
        validation_selection='two per structural stratum by raw input SHA; chosen before any labels',
        hardware=cfg, official_sha256=hashes(), solver_sha256=source_hashes(), training_jobs=jobs,
        fit={'lambda': .01, 'constraint': 'nonnegative coefficients', 'seed': None},
        old_scores_weights_or_plans_read=False,
        source_rule_priority='problem and appendices > reference paper > heuristics',
        protocol='current-round calibration; freeze model; fresh isolated inference; freeze plans; official acceptance')
    write(HERE / 'manifest.json', manifest)
    print(json.dumps({'training_jobs': len(jobs), 'validation': validation}), flush=True)


def evaluate(q, graph, plan):
    if str(OFFICIAL / 'code') not in sys.path: sys.path.insert(0, str(OFFICIAL / 'code'))
    cfg = read_hardware(CONFIG)
    kw = dict(bandwidth=cfg['bandwidth']['bandwidth'], capacity=cfg['capacity'])
    if q == 0:
        from singlecore_evaluate import evaluate_singlecore
        return evaluate_singlecore(graph, **kw)
    if q == 1:
        from multicore_cut_evaluate_problem_1 import evaluate_scene_a
        return evaluate_scene_a(graph, plan, **kw,
            cross_core_wait=cfg['multicore_scene_a']['task_cross_core_wait_cycles'],
            same_core_wait=cfg['multicore_scene_a']['task_same_core_wait_cycles'])
    kw['cross_core_copy_delay'] = cfg['multicore_scene_b']['cross_core_copy_delay_cycles']
    if q == 2:
        from multicore_cut_evaluate_problem_2 import evaluate_scene_b
        return evaluate_scene_b(graph, plan, **kw)
    from multicore_cut_evaluate_problem_3 import evaluate_problem_3
    return evaluate_problem_3(graph, plan, **kw, **cfg['problem_3'])


def compact(result):
    return {k: result[k] for k in ('makespan', 'data_movement_bytes', 'cache_stats') if k in result}


def save_raw(path, result):
    with gzip.open(path, 'wt', encoding='utf-8', compresslevel=1) as f:
        json.dump(result, f, separators=(',', ':'))


def label(job):
    folder = HERE / job['path']; start = time.perf_counter()
    assert digest(folder / 'plan.json') == job['plan_sha256']
    try:
        result = evaluate(job['question'], read_graph(job['case']), json.loads((folder / 'plan.json').read_text(encoding='utf-8')))
        save_raw(folder / 'official.json.gz', result)
        row = {**job, 'status': 'ok', **compact(result), 'seconds': time.perf_counter() - start}
        feature = json.loads((folder / 'features.json').read_text(encoding='utf-8'))['features']
        assert feature[0] <= result['makespan'] + 1e-6, 'physical lower bound violated'
    except Exception as exc:
        row = {**job, 'status': 'failed', 'error': repr(exc), 'seconds': time.perf_counter() - start}
    write(folder / 'label.json', row)
    return row


def fit(x, y, penalty):
    scale = np.sqrt(np.mean(x * x, axis=0)); scale[scale < 1e-12] = 1
    z = x / scale; gram = z.T @ z + penalty * np.eye(z.shape[1]); rhs = z.T @ y
    w = np.zeros(z.shape[1])
    for _ in range(4000):
        before = w.copy()
        for j in range(len(w)): w[j] = max(0., w[j] + (rhs[j] - gram[j] @ w) / gram[j, j])
        if np.max(np.abs(w - before)) < 1e-10: break
    return w / scale


def train(workers):
    manifest = preflight(); rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = []
        for job in manifest['training_jobs']:
            p = HERE / job['path'] / 'label.json'
            if p.exists():
                saved = json.loads(p.read_text(encoding='utf-8'))
                assert saved['plan_sha256'] == job['plan_sha256'] == digest(HERE / job['path'] / 'plan.json')
                rows.append(saved)
            else: futures.append(pool.submit(label, job))
        for f in as_completed(futures):
            row = f.result(); rows.append(row)
            if row['status'] != 'ok': print(json.dumps(row), flush=True)
            if len(rows) % 20 == 0: print('labels', len(rows), '/', len(manifest['training_jobs']), flush=True)
    rows.sort(key=lambda r: (r['question'], r['case'], r['cores'], r['name']))
    write(HERE / 'training_labels.json', rows)
    assert all(r['status'] == 'ok' for r in rows), 'inspect recorded training failures'
    model = dict(solver_version=VERSION, features=FEATURES, weights={}, solver_sha256=source_hashes(),
                 hardware_sha256=digest(CONFIG), fit=manifest['fit'], training_labels_sha256=digest(HERE / 'training_labels.json'),
                 origin='new labels for all three scenes, current round only')
    reports = {}
    for q in (1, 2, 3):
        data = [r for r in rows if r['question'] == q]
        x = np.array([json.loads((HERE / r['path'] / 'features.json').read_text(encoding='utf-8'))['features'] for r in data])
        y = np.array([r['makespan'] for r in data])
        assert np.all(x[:, 0] <= y + 1e-6), 'corrected physical lower bound violated'
        scales = {(r['case'], r['cores']): min(x[i, 0] for i, a in enumerate(data) if (a['case'], a['cores']) == (r['case'], r['cores'])) for r in data}
        s = np.array([max(1, scales[r['case'], r['cores']]) for r in data])
        w = fit(x / s[:, None], y / s, manifest['fit']['lambda'])
        cv = []
        for case in manifest['train']:
            held = np.array([r['case'] == case for r in data])
            wc = fit(x[~held] / s[~held, None], y[~held] / s[~held], manifest['fit']['lambda'])
            for n in manifest['train_cores']:
                ids = [i for i, r in enumerate(data) if r['case'] == case and r['cores'] == n]
                selected = min(ids, key=lambda i: (max(x[i, 0], x[i] @ wc), data[i]['name']))
                cv.append(dict(case=case, cores=n, relative_regret=float(y[selected] / min(y[ids]) - 1)))
        model['weights'][str(q)] = w.tolist()
        reports[str(q)] = dict(labels=len(data), weights=w.tolist(), group_cv=cv,
            mean_group_cv_regret=float(np.mean([r['relative_regret'] for r in cv])))
    write(HERE / 'model.json', model); write(HERE / 'fit_report.json', reports)
    print('MODEL_FROZEN', digest(HERE / 'model.json'), flush=True)


def generate():
    if (HERE / 'generation_freeze.json').exists():
        raise RuntimeError('plans already frozen: preserve this experiment; use a new directory')
    manifest = preflight(); jobs = []
    with tempfile.TemporaryDirectory(prefix='npu_fresh_') as temp:
        root = Path(temp)
        for file in ('solver.py', 'mechanism.py', 'model.json'): shutil.copy2(HERE / file, root / file)
        shutil.copy2(CONFIG, root / 'config.txt')
        # Isolated process admits only the copied package directory plus stdlib.
        launch = 'import sys,runpy; p=sys.argv.pop(1); sys.path.insert(0,p); runpy.run_path(p+"/solver.py",run_name="__main__")'
        for case in manifest['validation']:
            shutil.copy2(OFFICIAL / 'data' / (case + '.json'), root / 'unknown_graph.json')
            for q in manifest['questions']:
                for n in manifest['validation_cores']:
                    for method in ('component_scalar', 'trained'):
                        args = [sys.executable, '-I', '-c', launch, str(root), str(root / 'unknown_graph.json'), '-n', str(n), '--question', str(q),
                            '--config', str(root / 'config.txt'), '--model', str(root / 'model.json'), '--method', method,
                            '-o', str(root / 'answer.json'), '--report', str(root / 'generation.json')]
                        subprocess.run(args, cwd=root, check=True, capture_output=True, text=True)
                        path = Path('validation') / case / f'q{q}_n{n}' / method
                        (HERE / path).mkdir(parents=True, exist_ok=True)
                        shutil.copy2(root / 'answer.json', HERE / path / 'plan.json')
                        shutil.copy2(root / 'generation.json', HERE / path / 'generation.json')
                        sha = digest(root / 'answer.json')
                        # One independent repeated inference per scene/core count.
                        if case == manifest['validation'][0]:
                            (root / 'answer.json').unlink(); (root / 'generation.json').unlink()
                            subprocess.run(args, cwd=root, check=True, capture_output=True, text=True)
                            assert sha == digest(root / 'answer.json')
                        jobs.append(dict(case=case, question=q, cores=n, method=method, path=path.as_posix(), plan_sha256=sha))
            print('generated', case, flush=True)
    freeze = dict(model_sha256=digest(HERE / 'model.json'), solver_sha256=source_hashes(), jobs=jobs,
        generated_before_acceptance=True, isolated_renamed_input=True, repeat_30_plans_identical=True,
        official_calls_in_inference=0, time_ns=time.time_ns())
    write(HERE / 'generation_freeze.json', freeze)
    with zipfile.ZipFile(HERE / 'submission_solver.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for file in ('solver.py', 'mechanism.py', 'model.json'): z.write(HERE / file, file)
    print('ALL_PLANS_FROZEN', len(jobs), flush=True)


def accept_case(case):
    freeze = json.loads((HERE / 'generation_freeze.json').read_text(encoding='utf-8'))
    graph = read_graph(case); reference = evaluate(0, graph, None)['makespan']
    cache, rows, calls = {}, [], 1
    for job in [r for r in freeze['jobs'] if r['case'] == case]:
        folder = HERE / job['path']; assert digest(folder / 'plan.json') == job['plan_sha256']
        plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
        generation = json.loads((folder / 'generation.json').read_text(encoding='utf-8'))
        signature = json.dumps(plan, sort_keys=True)
        key = job['question'], signature
        try:
            if key not in cache:
                cache[key] = evaluate(job['question'], graph, plan); calls += 1
            result = cache[key]; save_raw(folder / 'official.json.gz', result)
            row = {**job, 'status': 'ok', **compact(result), 'reference_cycles': reference,
                'raw_speedup_vs_original_singlecore': reference / result['makespan'],
                'generation_seconds': generation['generation_seconds'], 'selected': generation['selected']}
            chosen = next(r for r in generation['candidates'] if r['name'] == generation['selected'])
            assert chosen['features'][0] <= result['makespan'] + 1e-6, 'physical bound violated'
            if job['question'] == 3:
                pair = 2, signature
                if pair not in cache: cache[pair] = evaluate(2, graph, plan); calls += 1
                row['same_plan_no_l2_cycles'] = cache[pair]['makespan']
                row['same_plan_cache_gain'] = cache[pair]['makespan'] / result['makespan']
                save_raw(folder / 'official_no_l2.json.gz', cache[pair])
        except Exception as exc:
            row = {**job, 'status': 'failed', 'error': repr(exc)}
        rows.append(row); write(folder / 'acceptance.json', row)
    write(HERE / 'validation' / case / 'completed.json', {'rows': rows, 'official_calls': calls})
    return rows, calls


def accept(workers):
    manifest = preflight(); freeze = json.loads((HERE / 'generation_freeze.json').read_text(encoding='utf-8'))
    assert digest(HERE / 'model.json') == freeze['model_sha256'] and source_hashes() == freeze['solver_sha256']
    rows, calls = [], 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = []
        for case in manifest['validation']:
            p = HERE / 'validation' / case / 'completed.json'
            if p.exists():
                obj = json.loads(p.read_text(encoding='utf-8'))
                expected = {(r['question'], r['cores'], r['method']): r['plan_sha256'] for r in freeze['jobs'] if r['case'] == case}
                actual = {(r['question'], r['cores'], r['method']): r['plan_sha256'] for r in obj['rows']}
                assert actual == expected, 'saved acceptance belongs to different frozen plans'
                for r in obj['rows']: assert digest(HERE / r['path'] / 'plan.json') == r['plan_sha256']
                rows.extend(obj['rows']); calls += obj['official_calls']
            else: futures.append(pool.submit(accept_case, case))
        for f in as_completed(futures):
            part, count = f.result(); rows.extend(part); calls += count
            print('accepted', part[0]['case'], len(part), 'failed', sum(r['status'] != 'ok' for r in part), flush=True)
            write(HERE / 'acceptance_progress.json', {'rows': len(rows), 'official_calls': calls, 'failures': [r for r in rows if r['status'] != 'ok']})
    rows.sort(key=lambda r: (r['question'], r['cores'], r['case'], r['method']))
    write(HERE / 'validation_results.json', rows)
    summary = dict(scope=manifest['scope'], validation_cases=manifest['validation'], total_plan_checks=len(rows),
        failed_jobs=[r for r in rows if r['status'] != 'ok'], official_acceptance_calls=calls,
        official_files_unchanged=len(hashes()), source_frozen=source_hashes() == freeze['solver_sha256'],
        model_frozen=digest(HERE / 'model.json') == freeze['model_sha256'], questions={})
    for q in manifest['questions']:
        cores = {}
        for n in manifest['validation_cores']:
            trained = [r for r in rows if r['question'] == q and r['cores'] == n and r['method'] == 'trained' and r['status'] == 'ok']
            initial = {r['case']: r for r in rows if r['question'] == q and r['cores'] == n and r['method'] == 'component_scalar' and r['status'] == 'ok'}
            changes = [1 - r['makespan'] / initial[r['case']]['makespan'] for r in trained if r['case'] in initial]
            entry = dict(cases=len(trained), arithmetic_mean_speedup=float(np.mean([r['raw_speedup_vs_original_singlecore'] for r in trained])),
                mean_paired_makespan_reduction=float(np.mean(changes)), improved=sum(v > 1e-9 for v in changes), regressed=sum(v < -1e-9 for v in changes),
                mean_generation_seconds=float(np.mean([r['generation_seconds'] for r in trained])))
            if q == 3: entry['mean_same_plan_cache_gain'] = float(np.mean([r['same_plan_cache_gain'] for r in trained]))
            cores[str(n)] = entry
        summary['questions'][str(q)] = cores
    assert manifest['official_sha256'] == hashes()
    write(HERE / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def screen():
    manifest = preflight(); cfg = read_hardware(CONFIG); count, failures = 0, []
    start = time.perf_counter()
    for p in sorted((OFFICIAL / 'data').glob('case_*.json')):
        if p.stem.count('_') != 1: continue
        g = Graph(json.loads(p.read_text(encoding='utf-8')))
        for n in (1, 2, 3, 4, 5):
            for q in (1, 2, 3):
                for name, plan in g.variants(n, cfg, q):
                    try: g.validate(plan, n); count += 1
                    except Exception as exc: failures.append(dict(case=p.stem, cores=n, question=q, name=name, error=repr(exc)))
    write(HERE / 'structural_screen.json', dict(cases=100, checks=count, failures=failures,
        official_calls=0, seconds=time.perf_counter() - start, solver_sha256=source_hashes(),
        meaning='coverage/ordering/acyclicity only, not full memory or execution acceptance'))
    print('STRUCTURAL_SCREEN', count, 'failures', len(failures), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('action', choices=['prepare', 'train', 'generate', 'accept', 'screen'])
    ap.add_argument('--workers', type=int, default=4); args = ap.parse_args()
    if args.action == 'prepare': prepare()
    elif args.action == 'train': train(args.workers)
    elif args.action == 'generate': generate()
    elif args.action == 'accept': accept(args.workers)
    else: screen()
