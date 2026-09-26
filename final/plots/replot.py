"""Regenerate all ten figures locally; no solver or official evaluator is run."""
from pathlib import Path
import runpy
for name in ['plot_2_to_7.py','plot_8.py']:
    runpy.run_path(str(Path(__file__).with_name(name)),run_name='__main__')
