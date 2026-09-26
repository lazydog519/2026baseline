"""Second holdout: freeze independent plans before calling official evaluator."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'all_questions_fresh_v3'
OFFICIAL = HERE.parent / 'official'
sys.path.insert(0, str(SOURCE))
from solver import Graph, read_hardware
from probe_neighbors import shortlist, sha
from selection_policy import choose
from calibrate_neighbors import official_hashes

CASES = ('case_011', 'case_057')
CORES = (2, 5)
QUESTIONS = (1, 2, 3)


def prepare():
    path = HERE / 'blind_holdout_frozen.json'
    model_path = HERE / 'neighbor_policy_frozen.json'
    model = json.loads(model_path.read_text(encoding='utf-8'))
    if path.exists():
        frozen = json.loads(path.read_text(encoding='utf-8'))
        assert frozen['policy_sha256'] == hashlib.sha256(model_path.read_bytes()).hexdigest()
        assert frozen['official_sha256'] == official_hashes()
        return frozen
    cfg = read_hardware(OFFICIAL / 'data' / 'config.txt')
    jobs = []
    for case in CASES:
        raw = json.loads((OFFICIAL / 'data' / f'{case}.json').read_text(encoding='utf-8'))
        g = Graph(raw)
        for n in CORES:
            for q in QUESTIONS:
                group, failures = shortlist(g, n, cfg, q)
                # Inference receives graph, fixed hardware and fresh-round global
                # coefficients only. It reads neither official result nor old plan.
                idx, scores = choose([{**row, 'cores': n} for row in group],
                                     model['coefficients'][str(q)], model['margin'])
                for i, row in enumerate(group):
                    jobs.append({'case': case, 'cores': n, 'question': q,
                                 'name': row['name'], 'plan': row['plan'],
                                 'plan_sha256': sha(row['plan']), 'proxy': row['proxy'],
                                 'selected': i == idx, 'selection_scores': scores,
                                 'generation_failures': failures})
    frozen = {'scope': 'new 2-case holdout selected after all policy rules frozen',
              'cases': CASES, 'policy_sha256': hashlib.sha256(model_path.read_bytes()).hexdigest(),
              'official_sha256': official_hashes(), 'jobs': jobs}
    path.write_text(json.dumps(frozen, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return frozen


def evaluate():
    data = prepare()
    labels = HERE / 'blind_holdout_labels.jsonl'
    done = {}
    if labels.exists():
        for line in labels.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            done[row['case'], row['cores'], row['question'], row['name']] = row
    from experiment import compact, evaluate as official_evaluate
    with labels.open('a', encoding='utf-8') as out:
        for i, job in enumerate(data['jobs'], 1):
            key = job['case'], job['cores'], job['question'], job['name']
            if key in done:
                continue
            assert sha(job['plan']) == job['plan_sha256']
            raw = json.loads((OFFICIAL / 'data' / f"{job['case']}.json").read_text(encoding='utf-8'))
            started = time.perf_counter()
            try:
                official = {'status': 'ok', **compact(official_evaluate(job['question'], raw, job['plan']))}
            except Exception as exc:
                official = {'status': 'failed', 'reason': repr(exc)}
            row = {k: v for k, v in job.items() if k not in ('plan', 'generation_failures')}
            row.update(official=official, seconds=time.perf_counter()-started)
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
            out.flush()
            print(f"{i}/{len(data['jobs'])} {job['case']} n{job['cores']} q{job['question']} "
                  f"{job['name']} {'*' if job['selected'] else ''} "
                  f"{official.get('makespan', official['status'])}", flush=True)
    assert data['official_sha256'] == official_hashes()
    print(f'official_files_unchanged={len(data["official_sha256"])}', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--prepare-only', action='store_true')
    args = ap.parse_args()
    data = prepare()
    print(f'frozen_jobs={len(data["jobs"])} selected={sum(x["selected"] for x in data["jobs"])}', flush=True)
    if not args.prepare_only:
        evaluate()
