#!/usr/bin/env python3
"""Preserve pre-refactor CLI, acknowledgement and reconstruction contracts."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import cleanup_arguments
from cleanup_actions import _configuration_acknowledgements
from cleanup_errors import CleanupError
import cleanup_files
import cleanup_obsolete_riding
from cleanup_plans import snapshot
import cleanup_shaman_dual_wield
from cleanup_workspace import Workspace


def parser_contract(parser):
    """Describe CLI behavior independently of argparse's help line wrapping."""
    actions = []
    for action in parser._actions:
        choices = action.choices
        if isinstance(choices, dict):
            choices = {
                name: parser_contract(child) for name, child in choices.items()
            }
        elif choices is not None:
            choices = list(choices)
        actions.append({
            "action": type(action).__name__,
            "options": action.option_strings,
            "dest": action.dest,
            "nargs": action.nargs,
            "default": action.default,
            "required": action.required,
            "help": action.help,
            "metavar": action.metavar,
            "type": getattr(action.type, "__name__", None),
            "choices": choices,
        })
    return {"description": parser.description, "actions": actions}


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = json.loads(
            (ROOT / "tests/fixtures/python-refactor-contracts.json").read_text(
            )
        )
        spec = importlib.util.spec_from_file_location(
            "spell_contract_fixtures", ROOT / "tests/spell-state-tests.py"
        )
        cls.spell_tests = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.spell_tests)
        cls.spell_tests.SpellTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.spell_tests.SpellTests.tearDownClass()

    def test_cli_declarations_match_original_contract(self):
        actual = parser_contract(cleanup_arguments.parser())
        self.assertEqual(actual, self.contracts["cli_contract"])

    def test_riding_planning_retains_the_native_defaults_reader(self):
        self.assertIs(
            cleanup_obsolete_riding.defaults,
            cleanup_shaman_dual_wield.defaults,
        )

    def test_acknowledgement_sql_and_failure_precedence_match_original(self):
        for case in self.contracts["acknowledgements"]:
            manifest = case["manifest"]
            with self.subTest(policy=manifest["policy"]):
                self.assertEqual(
                    _configuration_acknowledgements(manifest), case["sql"]
                )
            for field, expected in case["missing_fields"].items():
                with self.subTest(policy=manifest["policy"], missing=field):
                    incomplete = dict(manifest)
                    del incomplete[field]
                    with self.assertRaises(CleanupError) as raised:
                        _configuration_acknowledgements(incomplete)
                    self.assertEqual(raised.exception.code, expected["code"])
                    self.assertEqual(str(raised.exception), expected[
                        "message"])
                    self.assertEqual(raised.exception.hint, expected["hint"])

    def test_reconstruction_and_rejections_match_original_without_mutation(
        self,
    ):
        converter = self.spell_tests.SpellTests()
        for index, case in enumerate(self.contracts["spells"]):
            with self.subTest(case=index):
                arguments = copy.deepcopy(case["inputs"])
                for name in ("stored", "skills", "talents"):
                    if name in arguments:
                        arguments[name] = {
                            int(key): tuple(value) if isinstance(value, list)
                            else value
                            for key, value in arguments[name].items()
                        }
                before = copy.deepcopy(arguments)
                try:
                    rows = converter.convert(**arguments)
                except self.spell_tests.Unsupported as error:
                    actual = {"reason": error.reason, "detail": str(error)}
                else:
                    actual = {"rows": rows}
                self.assertEqual(json.loads(json.dumps(actual)), case[
                    "expected"])
                self.assertEqual(arguments, before)

    def test_policy_description_catalog_preserves_original_text(self):
        descriptions = json.loads(
            (ROOT / "lib/cleanup_policy_descriptions.json").read_text()
        )
        digest = hashlib.sha256(json.dumps(
            descriptions, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        self.assertEqual(digest, self.contracts["policy_descriptions_sha256"])

    def test_extracted_dependencies_cannot_escape_batch_integrity_checks(self):
        expected = {
            str(path.relative_to(ROOT))
            for directory in ("lib", "tools", "bin")
            for path in (ROOT / directory).glob("*.py")
        }
        self.assertTrue(expected <= set(cleanup_files.IMPLEMENTATION_FILES))
        self.assertIn(
            "lib/cleanup_policy_descriptions.json",
            cleanup_files.IMPLEMENTATION_FILES,
        )
        hashes = cleanup_files.implementation_hashes()
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            package = session / "batches" / "candidate"
            package.mkdir(parents=True)
            manifest = {
                "cleanup_session": session.name,
                "implementation_sha256": hashes,
            }
            cleanup_files.write_json(package / "manifest.json", manifest)
            cleanup_files.seal(package)
            work = Workspace(type("Settings", (), {"workspace": session})())
            work.session = session
            self.assertEqual(work.batch("candidate")[1], manifest)
            changed = dict(hashes)
            changed["lib/spell_reconstruction.py"] = "0" * 64
            with patch.object(
                cleanup_files, "implementation_hashes", return_value=changed
            ):
                with self.assertRaises(CleanupError) as raised:
                    work.batch("candidate")
                self.assertEqual(
                    raised.exception.code, "TOOLKIT_IMPLEMENTATION_DRIFT"
                )

    def test_generation_rejects_implementation_changes_since_operation_start(
        self,
    ):
        hashes = cleanup_files.implementation_hashes()
        with tempfile.TemporaryDirectory() as directory:
            operation = Path(directory)
            hashes["lib/spell_reconstruction.py"] = "0" * 64
            cleanup_files.write_json(
                operation / "operation.json", {"toolkit_sha256": hashes}
            )
            with self.assertRaises(CleanupError) as raised:
                cleanup_files.implementation_hashes(operation)
            self.assertEqual(
                raised.exception.code, "TOOLKIT_IMPLEMENTATION_DRIFT"
            )

    def test_legacy_manifests_retain_existing_integrity_path(self):
        with patch.object(cleanup_files, "implementation_hashes") as hashes:
            cleanup_files.verify_implementation_hashes({"policy": "legacy"})
        hashes.assert_not_called()

    def test_snapshot_session_prefix_is_explicit_and_does_not_replace_runner(
        self,
    ):
        class Runner:
            def sql(self, query, role='audit', headers=False):
                self.query = query
                return '{"kind":"rows","value":[1]}\n'

        runner = Runner()
        original = runner.sql.__func__
        prefix = "SET SESSION group_concat_max_len=640001;\n"
        result = snapshot(
            runner, [("rows", "SELECT JSON_ARRAY(1) row_value")],
            session_prefix=prefix,
        )
        self.assertEqual(result, {"rows": [[1]]})
        self.assertIs(runner.sql.__func__, original)
        self.assertTrue(runner.query.startswith(prefix))
        self.assertTrue(runner.query.endswith("ROLLBACK;"))

    def test_production_syntax_and_signatures_remain_python310_compatible(
        self,
    ):
        for directory in ("lib", "tools", "bin"):
            for path in (ROOT / directory).glob("*.py"):
                tree = ast.parse(path.read_text(), feature_version=(3, 10))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.FunctionDef):
                        continue
                    with self.subTest(path=path.name, function=node.name):
                        self.assertIsNotNone(node.returns)
                        arguments = [
                            *node.args.posonlyargs, *node.args.args,
                            *node.args.kwonlyargs,
                        ]
                        for argument in arguments:
                            if argument.arg not in ("self", "cls"):
                                self.assertIsNotNone(argument.annotation)


if __name__ == "__main__":
    unittest.main()
