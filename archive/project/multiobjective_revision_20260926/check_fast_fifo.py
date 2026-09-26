"""Compare the heap FIFO against the original analytical trace routine."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
old_path = HERE.parent / 'all_questions_fresh_v3' / 'mechanism.py'
spec = importlib.util.spec_from_file_location('old_mechanism', old_path)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
sys.path.insert(0, str(HERE / 'standalone_pilot'))
from fast_fifo import fifo_trace


def main():
    for seed in range(100):
        rng = random.Random(seed)
        trace = [((rng.randrange(0, 40) if seed % 2 else rng.randrange(0, 40)+rng.random()),
                  rng.randrange(0, 12),
                  rng.choice((0, 8, 16, 32, 64, 128)), rng.randrange(0, 4) != 0)
                 for _ in range(rng.randrange(1, 100))]
        a = old.fifo_trace(trace, 256, 60, 250)
        b = fifo_trace(trace, 256, 60, 250)
        for key in a:
            if key == 'trace_end':
                assert abs(a[key]-b[key]) < 1e-6, (seed, key, a[key], b[key])
            else:
                assert a[key] == b[key], (seed, key, a[key], b[key])
    print('100 randomized traces: same hit, DDR, FIFO and finish results')


if __name__ == '__main__':
    main()
