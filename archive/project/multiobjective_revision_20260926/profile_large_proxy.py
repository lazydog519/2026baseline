"""Development timing probe for one large graph; no evaluator access."""
import faulthandler
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'standalone_pilot'))
from graph_primitives import Graph, read_hardware
from stage_candidates import stage_plan

def main():
    root = HERE.parent / 'official' / 'data'
    g = Graph(json.loads((root / 'case_014.json').read_text(encoding='utf-8')))
    cfg = read_hardware(root / 'config.txt')
    faulthandler.dump_traceback_later(10, repeat=True)
    start = time.perf_counter()
    plan = stage_plan(g, 2, 'depth_band')
    print('stage_seconds', time.perf_counter()-start, flush=True)
    start = time.perf_counter()
    features, detail = g.features(plan, cfg, 3)
    print('features_seconds', time.perf_counter()-start, 'features', features, flush=True)
    faulthandler.cancel_dump_traceback_later()

if __name__ == '__main__':
    main()
