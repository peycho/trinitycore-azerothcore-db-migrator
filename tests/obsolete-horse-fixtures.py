"""Reuse native riding fixture construction with the separate fixed Horse catalog."""
import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('horse_riding_fixture',ROOT/'tests/obsolete-riding-fixtures.py')
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
legacy.RULES=json.loads((ROOT/'lib/cleanup_obsolete_horse_catalog.json').read_text())
base=legacy.base
world=legacy.world
seed=legacy.seed
