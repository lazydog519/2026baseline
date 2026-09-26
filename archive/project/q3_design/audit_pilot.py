"""Replay recorded FIFO events; test the frozen solver in an isolated directory."""
import csv
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
P = ROOT.parent


def read_result(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def replay(result):
    queue = OrderedDict()
    opened = {}
    windows = []
    counts = dict(hit_bytes=0, miss_bytes=0, copy_in_hits=0, copy_in_misses=0)
    used = 0
    evictions = 0
    last_time = -1
    for i, event in enumerate(result['cache_events']):
        tid, size = event['tensor_id'], event['size_bytes']
        assert event['time'] >= last_time
        last_time = event['time']
        if event['event'] in ('hit', 'miss'):
            hit = event['event'] == 'hit'
            assert hit == (tid in queue), (i, event)
            counts['hit_bytes' if hit else 'miss_bytes'] += size
            counts['copy_in_hits' if hit else 'copy_in_misses'] += 1
        else:
            assert event['event'] == 'insert' and tid not in queue
            assert size <= result['cache_capacity_bytes']
            popped = []
            while used + size > result['cache_capacity_bytes']:
                old, amount = queue.popitem(last=False)
                used -= amount
                popped.append(old)
                row = opened.pop(old)
                row.update(end_event=i, end_cycle=event['time'], evicted=True)
                windows.append(row)
            assert popped == event['evicted_tensor_ids']
            evictions += len(popped)
            queue[tid] = size
            used += size
            assert used == event['used_bytes']
            opened[tid] = dict(tensor_id=tid, size_bytes=size, start_event=i,
                              start_cycle=event['time'])
    for row in opened.values():
        row.update(end_event=len(result['cache_events']),
                   end_cycle=result['makespan'], evicted=False)
        windows.append(row)
    assert used == result['cache_used_bytes_final']
    assert list(queue.items()) == [(x['tensor_id'], x['size_bytes'])
                                  for x in result['cache_final_entries']]
    for k, value in counts.items():
        assert value == result['cache_stats'][k], k
    windows.sort(key=lambda r: r['start_event'])
    return windows, dict(events=len(result['cache_events']), evictions=evictions,
                         residence_episodes=len(windows), **counts)


def main():
    frozen = json.loads((ROOT/'pilot_frozen_manifest.json').read_text())
    for name, digest in frozen['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest
    official = json.loads((P/'official_manifest.json').read_text(encoding='utf-8'))
    for entry in official['files']:
        assert hashlib.sha256((P/'official'/entry['path']).read_bytes()).hexdigest() == entry['sha256']
    audits = []
    all_windows = []
    for phase in ('development', 'diagnostic', 'confirmation'):
        for path in sorted((ROOT/phase).glob('case_*/n*/selected_result.json.gz')):
            result = read_result(path)
            windows, stats = replay(result)
            identity = dict(phase=phase, case=path.parent.parent.name,
                            cores=int(path.parent.name[1:]),
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            audits.append(dict(**identity, **stats, passed=True))
            all_windows.extend(dict(version='fifo-event-replay-v1', **identity, **r)
                               for r in windows)
    with (ROOT/'cache_windows.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(all_windows[0]))
        w.writeheader(); w.writerows(all_windows)
    # The temporary directory contains source + a renamed input only. There is
    # no result directory, historical solution, case ID lookup or source dataset.
    with tempfile.TemporaryDirectory(prefix='q3_isolated_') as temp:
        isolated = Path(temp)
        for subdir in ('q3_design', 'solution', 'official/code'):
            (isolated/subdir).mkdir(parents=True, exist_ok=True)
        for name in ('q3_pilot_solver.py', 'pilot_config.json'):
            shutil.copyfile(ROOT/name, isolated/'q3_design'/name)
        for name in ('baseline.py', 'q1_optimized.py'):
            shutil.copyfile(P/'solution'/name, isolated/'solution'/name)
        for source in (P/'official/code').glob('*.py'):
            shutil.copyfile(source, isolated/'official/code'/source.name)
        shutil.copyfile(P/'official/data/case_044.json', isolated/'renamed_input.json')
        shutil.copyfile(P/'official/data/config.txt', isolated/'config.txt')
        process = subprocess.run([sys.executable, '-X', 'utf8',
            str(isolated/'q3_design/q3_pilot_solver.py'), str(isolated/'renamed_input.json'),
            '-n', '2', '--output-dir', str(isolated/'new_output')],
            cwd=isolated, capture_output=True, text=True)
        assert process.returncode == 0, process.stderr
        expected = ROOT/'diagnostic/case_044/n2'
        assert json.loads((isolated/'new_output/plan.json').read_text()) == json.loads((expected/'plan.json').read_text())
        assert read_result(isolated/'new_output/selected_result.json.gz') == read_result(expected/'selected_result.json.gz')
        reproduction = dict(input_renamed=True, historical_results_present=False,
            new_process=True, fresh_output=True, entire_plan_equal=True,
            entire_official_result_equal=True, test_case='case_044', cores=2,
            makespan=45906)
    report = dict(version='q3-pilot-audit-v1', jobs=len(audits),
        official_source_files_unchanged=len(official['files']),
        frozen_sources_unchanged=True, all_fifo_replays_passed=True,
        total_evictions=sum(a['evictions'] for a in audits),
        isolated_reproduction=reproduction, records=audits,
        limitation='Event replay validates the model against saved official events; it is not an independent performance simulator.')
    (ROOT/'audit_results.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'}))


if __name__ == '__main__':
    main()
