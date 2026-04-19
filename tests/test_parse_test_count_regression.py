import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / ".agents" / "skills" / "code-impact-guardian" / "scripts"))

from after_edit_update import parse_test_count, run_tests_with_coverage


class ParseTestCountRegressionTest(unittest.TestCase):
    def test_parse_test_count_matrix(self):
        cases = [
            ("unittest", "Ran 2 tests in 0.01s\nOK\n", "python", 2, "parsed"),
            ("pytest", "1 failed, 3 passed in 0.12s\n", "python", 4, "parsed"),
            ("node tap", "TAP version 13\n# tests 5\n# pass 5\n", "tsjs", 5, "parsed"),
            ("vitest tests only", "Tests 3 passed (3)\n", "tsjs", 3, "parsed"),
            (
                "vitest suite summary is ignored",
                "Test Files 1 passed (1)\nTests 3 passed (3)\n",
                "tsjs",
                3,
                "parsed",
            ),
            ("vitest suite summary alone stays unknown", "Test Files 1 passed (1)\n", "tsjs", None, "unknown"),
            (
                "jest suite summary is ignored",
                "Test Suites: 1 passed, 1 total\nTests: 4 passed, 4 total\n",
                "tsjs",
                4,
                "parsed",
            ),
            ("jest suite summary alone stays unknown", "Test Suites: 1 passed, 1 total\n", "tsjs", None, "unknown"),
            ("duplicate error labels are deduped", "2 error\n2 errors\n", "python", 2, "parsed"),
            ("unknown output stays unknown", "nothing to count here\n", "python", None, "unknown"),
        ]

        for label, output, adapter_name, expected_count, expected_status in cases:
            with self.subTest(label=label):
                tests_run, test_count_status = parse_test_count(output, adapter_name)
                self.assertEqual(tests_run, expected_count)
                self.assertEqual(test_count_status, expected_status)

    def test_no_test_command_stays_skipped(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        base_config = json.loads((repo_root / ".code-impact-guardian" / "config.json").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = pathlib.Path(tmp)
            (workspace_root / ".ai" / "codegraph").mkdir(parents=True, exist_ok=True)
            (workspace_root / ".code-impact-guardian").mkdir(parents=True, exist_ok=True)
            (workspace_root / "src").mkdir(parents=True, exist_ok=True)
            (workspace_root / "src" / "settings.conf").write_text("mode=active\n", encoding="utf-8")

            base_config["project_root"] = "."
            base_config["primary_adapter"] = "generic"
            base_config["language_adapter"] = "generic"
            base_config["generic"]["test_command"] = []

            config_path = workspace_root / ".code-impact-guardian" / "config.json"
            config_path.write_text(json.dumps(base_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            summary = run_tests_with_coverage(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id="no-tests",
            )
            self.assertEqual(summary["status"], "skipped")
            self.assertFalse(summary["tests_passed"])
            self.assertIsNone(summary["tests_run"])
            self.assertEqual(summary["test_count_status"], "unknown")
            self.assertIn("no test command configured", summary["coverage_reason"])
