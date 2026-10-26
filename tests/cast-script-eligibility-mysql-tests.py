#!/usr/bin/env python3
"""Run guarded eligibility lifecycle with reviewed cast callbacks enabled."""
import importlib.util
from pathlib import Path
p=Path(__file__).with_name('spell-eligibility-mysql-tests.py')
spec=importlib.util.spec_from_file_location('cast_callback_lifecycle',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
if __name__=='__main__':m.main(reviewed_cast_scripts=True)
