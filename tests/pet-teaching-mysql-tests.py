#!/usr/bin/env python3
"""Run the shared two-world transaction suite with pet teachers and retained pets."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('repair_mysql',Path(__file__).with_name('spell-eligibility-mysql-tests.py'))
suite=importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)

if __name__=='__main__':
    suite.main(pet_teaching=True)
