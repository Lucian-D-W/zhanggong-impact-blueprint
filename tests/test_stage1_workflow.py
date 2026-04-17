import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing


class Stage1WorkflowTest(unittest.TestCase):
    def test_stage1_template_uses_json_config_and_gitignore(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        config_json = repo_root / ".code-impact-guardian" / "config.json"
        config_yaml = repo_root / ".code-impact-guardian" / "config.yaml"
        gitignore = repo_root / ".gitignore"

        self.assertTrue(config_json.exists(), "config should be explicitly named as JSON")
        self.assertFalse(config_yaml.exists(), "misleading config.yaml should not remain")
        self.assertTrue(gitignore.exists(), ".gitignore must exist")

        gitignore_text = gitignore.read_text(encoding="utf-8")
        for expected in (".ai/", "__pycache__/", "*.pyc", ".coverage", "coverage-*.json"):
            self.assertIn(expected, gitignore_text)

    def test_stage1_demo_generates_db_report_and_results(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        demo_script = repo_root / "scripts" / "demo_phase1.py"
        self.assertTrue(demo_script.exists(), "demo script must exist")
        original_app_text = (repo_root / "examples" / "python_minimal" / "src" / "app.py").read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = pathlib.Path(tmp) / "demo-copy"
            subprocess.run(
                [sys.executable, str(demo_script), "--workspace", str(temp_repo)],
                check=True,
                cwd=repo_root,
            )

            db_path = temp_repo / ".ai" / "codegraph" / "codegraph.db"
            report_path = temp_repo / ".ai" / "codegraph" / "reports" / "impact-demo-login-impact.md"
            test_results = temp_repo / ".ai" / "codegraph" / "test-results.json"

            self.assertTrue(db_path.exists())
            self.assertTrue(report_path.exists())
            self.assertTrue(test_results.exists())

            edited_app_text = (temp_repo / "examples" / "python_minimal" / "src" / "app.py").read_text(encoding="utf-8")
            self.assertNotEqual(
                edited_app_text,
                original_app_text,
                "demo should leave behind a real code edit in the copied workspace",
            )

            with closing(sqlite3.connect(db_path)) as conn:
                node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                self.assertGreater(node_count, 0)
                self.assertGreater(edge_count, 0)

            payload = json.loads(test_results.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["coverage_status"], "available")

            list_seeds_script = temp_repo / ".agents" / "skills" / "code-impact-guardian" / "scripts" / "list_seeds.py"
            self.assertTrue(list_seeds_script.exists(), "seed listing script must exist")
            seed_output = subprocess.check_output(
                [sys.executable, str(list_seeds_script), "--workspace-root", str(temp_repo), "--config", str(temp_repo / ".code-impact-guardian" / "config.json")],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn("fn:src/app.py:login", seed_output)


if __name__ == "__main__":
    unittest.main()
