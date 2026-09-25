"""Evaluator-free 100-graph, 2–5-core structural screen for the pilot policy."""
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'standalone_pilot'
OFFICIAL = HERE.parent / 'official'
sys.path.insert(0, str(SOURCE))
from graph_primitives import Graph, read_hardware
from candidate_family import shortlist
from selection_policy import choose


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def main():
    cfg = read_hardware(OFFICIAL / 'data/config.txt')
    policy = json.loads((SOURCE / 'model.json').read_text(encoding='utf-8'))
    path = HERE / 'structural_100_progress.jsonl'
    done = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row['status'] == 'valid':
                done[row['case'], row['cores'], row['question']] = row
    files = sorted((OFFICIAL / 'data').glob('case_*.json'))
    files = [p for p in files if p.stem.count('_') == 1]
    assert len(files) == 100
    with path.open('a', encoding='utf-8') as out:
        for file in files:
            raw = json.loads(file.read_text(encoding='utf-8'))
            g = Graph(raw)
            for n in range(2, 6):
                for q in (1, 2, 3):
                    key = file.stem, n, q
                    if key in done:
                        continue
                    started = time.perf_counter()
                    try:
                        group, failures = shortlist(g, n, cfg, q)
                        idx = choose(
                            [{**row, 'cores': n} for row in group],
                            policy['coefficients'][str(q)], policy['margin'])[0]
                        g.validate(group[idx]['plan'], n)
                        result = {'status': 'valid', 'candidate_count': len(group),
                                  'selected': group[idx]['name'],
                                  'selected_plan_sha256': sha(group[idx]['plan']),
                                  'rejected_moves': len(failures)}
                    except Exception as exc:
                        result = {'status': 'failed', 'reason': repr(exc)}
                    row = {'case': file.stem, 'cores': n, 'question': q,
                           'graph_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                           **result, 'generation_seconds': time.perf_counter()-started}
                    out.write(json.dumps(row, ensure_ascii=False) + '\n'); out.flush()
                    if row['status'] != 'valid':
                        print(key, row['reason'], flush=True)
    attempts = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    latest = {(r['case'], r['cores'], r['question']): r for r in attempts}
    rows = [r for r in latest.values() if r['cores'] >= 2]
    report = {'scope': '100 official input graphs x 4 optimized core counts (2–5) x 3 questions; structural only',
              'groups': len(rows), 'valid_groups': sum(r['status'] == 'valid' for r in rows),
              'failed_groups': sum(r['status'] != 'valid' for r in rows),
              'official_calls': 0,
              'prior_failed_attempts_recovered': sum(r['status'] != 'valid' and r['cores'] >= 2 for r in attempts) -
                                                 sum(r['status'] != 'valid' for r in rows),
              'excluded_singlecore_attempt_records': sum(r['cores'] == 1 for r in attempts),
              'total_generation_seconds': sum(r['generation_seconds'] for r in rows),
              'maximum_generation_seconds': max(r['generation_seconds'] for r in rows)}
    (HERE / 'structural_100_summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(report, flush=True)


if __name__ == '__main__':
    main()
