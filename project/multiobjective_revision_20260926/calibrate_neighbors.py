"""Fresh development labels for bounded graph moves; excluded from submission.

Candidate plans and the train/holdout split are fixed before official calls.
This file only screens whether the added move family is worth implementing.
"""
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

TRAIN = ('case_071', 'case_046', 'case_001', 'case_026', 'case_093', 'case_064')
HOLDOUT = ('case_032', 'case_052')
CORES = (2, 5)
QUESTIONS = (1, 2, 3)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def official_hashes():
    return {p.relative_to(OFFICIAL).as_posix(): file_hash(p)
            for p in OFFICIAL.rglob('*') if p.is_file() and p.suffix != '.pyc'
            and '__pycache__' not in p.parts}


def prepare():
    path = HERE / 'neighbor_candidates_frozen.json'
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        assert data['train'] == list(TRAIN) and data['holdout'] == list(HOLDOUT)
        assert official_hashes() == data['official_sha256']
        return data
    cfg = read_hardware(OFFICIAL / 'data' / 'config.txt')
    jobs = []
    for case in (*TRAIN, *HOLDOUT):
        raw = json.loads((OFFICIAL / 'data' / f'{case}.json').read_text(encoding='utf-8'))
        g = Graph(raw)
        for n in CORES:
            for q in QUESTIONS:
                picked, failures = shortlist(g, n, cfg, q)
                for row in picked:
                    jobs.append({'case': case, 'question': q, 'cores': n,
                                 'name': row['name'], 'proxy': row['proxy'],
                                 'plan_sha256': sha(row['plan']),
                                 'plan': row['plan'],
                                 'candidate_generation_failures': failures})
    data = {'scope': 'fresh bounded-move development, 6 train/2 untouched holdout graphs',
            'train': TRAIN, 'holdout': HOLDOUT, 'cores': CORES, 'questions': QUESTIONS,
            'official_sha256': official_hashes(),
            'source_sha256': {p.name: file_hash(p) for p in
                              (HERE / 'structural_neighbors.py', HERE / 'probe_neighbors.py',
                               HERE / 'calibrate_neighbors.py')},
            'jobs': jobs}
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return data


def run():
    data = prepare()
    labels = HERE / 'neighbor_calibration_labels.jsonl'
    done = {}
    if labels.exists():
        for line in labels.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            done[row['plan_sha256'], row['question']] = row
    assert official_hashes() == data['official_sha256']
    from experiment import compact, evaluate
    with labels.open('a', encoding='utf-8') as out:
        for i, job in enumerate(data['jobs'], 1):
            key = job['plan_sha256'], job['question']
            if key in done:
                continue
            assert sha(job['plan']) == job['plan_sha256']
            raw = json.loads((OFFICIAL / 'data' / f"{job['case']}.json").read_text(encoding='utf-8'))
            started = time.perf_counter()
            try:
                result = {'status': 'ok', **compact(evaluate(job['question'], raw, job['plan']))}
            except Exception as exc:
                result = {'status': 'failed', 'reason': repr(exc)}
            row = {k: v for k, v in job.items() if k not in ('plan', 'candidate_generation_failures')}
            row.update(official=result, seconds=time.perf_counter()-started)
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
            out.flush()
            print(f"{i}/{len(data['jobs'])} {job['case']} n{job['cores']} q{job['question']} "
                  f"{job['name']} {result.get('makespan', result['status'])}", flush=True)
    assert official_hashes() == data['official_sha256']
    print(f'official_files_unchanged={len(data["official_sha256"])}; jobs={len(data["jobs"])}', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--prepare-only', action='store_true')
    args = ap.parse_args()
    if args.prepare_only:
        data = prepare()
        print({'jobs': len(data['jobs']), 'train': TRAIN, 'holdout': HOLDOUT})
    else:
        run()
