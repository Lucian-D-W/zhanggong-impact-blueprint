import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing


class Stage2WorkflowTest(unittest.TestCase):
    def test_cig_tsjs_demo_runs_end_to_end(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "code-impact-guardian" / "cig.py"
        self.assertTrue(cig_script.exists(), "cig.py must exist")

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = pathlib.Path(tmp) / "tsjs-copy"
            subprocess.run(
                [
                    sys.executable,
                    str(cig_script),
                    "demo",
                    "--fixture",
                    "tsjs_minimal",
                    "--workspace",
                    str(temp_repo),
                ],
                check=True,
                cwd=repo_root,
            )

            detect_output = subprocess.check_output(
                [
                    sys.executable,
                    str(cig_script),
                    "detect",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn('"detected_adapter": "tsjs"', detect_output)

            seed_output = subprocess.check_output(
                [
                    sys.executable,
                    str(cig_script),
                    "seeds",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn("fn:src/math.js:add", seed_output)

            db_path = temp_repo / ".ai" / "codegraph" / "codegraph.db"
            report_path = temp_repo / ".ai" / "codegraph" / "reports" / "impact-demo-tsjs-impact.md"
            test_results = temp_repo / ".ai" / "codegraph" / "test-results.json"

            self.assertTrue(db_path.exists())
            self.assertTrue(report_path.exists())
            self.assertTrue(test_results.exists())

            with closing(sqlite3.connect(db_path)) as conn:
                function_count = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE kind = 'function' AND path LIKE 'src/%'"
                ).fetchone()[0]
                test_count = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE kind = 'test' AND path LIKE 'tests/%'"
                ).fetchone()[0]
                call_count = conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE edge_type = 'CALLS'"
                ).fetchone()[0]
                self.assertGreater(function_count, 0)
                self.assertGreater(test_count, 0)
                self.assertGreater(call_count, 0)

            payload = json.loads(test_results.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "passed")

    def test_cig_generic_demo_runs_file_level_fallback(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "code-impact-guardian" / "cig.py"
        self.assertTrue(cig_script.exists(), "cig.py must exist")

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = pathlib.Path(tmp) / "generic-copy"
            subprocess.run(
                [
                    sys.executable,
                    str(cig_script),
                    "demo",
                    "--fixture",
                    "generic_minimal",
                    "--workspace",
                    str(temp_repo),
                ],
                check=True,
                cwd=repo_root,
            )

            detect_output = subprocess.check_output(
                [
                    sys.executable,
                    str(cig_script),
                    "detect",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn('"detected_adapter": "generic"', detect_output)

            seed_output = subprocess.check_output(
                [
                    sys.executable,
                    str(cig_script),
                    "seeds",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn("file:src/settings.conf", seed_output)
            self.assertNotIn('"functions": [', seed_output.replace("\r\n", "\n"))

            db_path = temp_repo / ".ai" / "codegraph" / "codegraph.db"
            report_path = temp_repo / ".ai" / "codegraph" / "reports" / "impact-demo-generic-impact.md"
            test_results = temp_repo / ".ai" / "codegraph" / "test-results.json"

            self.assertTrue(db_path.exists())
            self.assertTrue(report_path.exists())
            self.assertTrue(test_results.exists())

            with closing(sqlite3.connect(db_path)) as conn:
                file_count = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'file'").fetchone()[0]
                function_count = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'function'").fetchone()[0]
                self.assertGreater(file_count, 0)
                self.assertEqual(function_count, 0)

            payload = json.loads(test_results.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "passed")


if __name__ == "__main__":
    unittest.main()
