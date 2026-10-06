"""Load the preserved experimental package for the offline contract suite."""

import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "bootstrap.py"
spec = importlib.util.spec_from_file_location("jev_experiment_bootstrap", path)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
bootstrap.activate()
