#!/usr/bin/env python3
"""Run the shared two-world transaction suite with pet teachers and retained pets."""
import importlib.util
import sys
from pathlib import Path

spec=importlib.util.spec_from_file_location('repair_mysql',Path(__file__).with_name('spell-eligibility-mysql-tests.py'))
suite=importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)

if __name__=='__main__':
    assert sys.argv[1:] in ([],['--reviewed-cower'])
    suite.main(pet_teaching=True,reviewed_cower=bool(sys.argv[1:]))
