import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing


class Stage3WorkflowTest(unittest.TestCase):
    def test_init_and_doctor_work_for_skill_only_copy(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        skill_dir = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint"

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = pathlib.Path(tmp) / "skill-only-copy"
            (temp_repo / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill_dir, temp_repo / ".agents" / "skills" / "zhanggong-impact-blueprint")
            (temp_repo / "src").mkdir(parents=True, exist_ok=True)
            (temp_repo / "tests").mkdir(parents=True, exist_ok=True)
            (temp_repo / "docs" / "rules").mkdir(parents=True, exist_ok=True)

            (temp_repo / "src" / "app.py").write_text(
                "def login(username, password):\n    return bool(username and password)\n",
                encoding="utf-8",
            )
            (temp_repo / "tests" / "test_app.py").write_text(
                "import unittest\nfrom src.app import login\n\n\nclass LoginTest(unittest.TestCase):\n    def test_login(self):\n        self.assertTrue(login('demo', 'secret'))\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
                encoding="utf-8",
            )
            (temp_repo / "docs" / "rules" / "auth.md").write_text(
                "---\nid: auth.basic\ngoverns:\n  - fn:src/app.py:login\n---\nRequire a username and password.\n",
                encoding="utf-8",
            )

            cig_script = temp_repo / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
            init_cmd = [
                sys.executable,
                str(cig_script),
                "init",
                "--workspace-root",
                str(temp_repo),
            ]
            subprocess.run(init_cmd, check=True, cwd=temp_repo)
            subprocess.run(init_cmd, check=True, cwd=temp_repo)

            self.assertTrue((temp_repo / ".zhanggong-impact-blueprint" / "config.json").exists())
            self.assertTrue((temp_repo / ".zhanggong-impact-blueprint" / "schema.sql").exists())
            self.assertTrue((temp_repo / ".ai" / "codegraph").exists())

            doctor_output = subprocess.check_output(
                [
                    sys.executable,
                    str(cig_script),
                    "doctor",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn("PASS", doctor_output)
            self.assertNotIn("FAIL", doctor_output)

    def test_after_edit_records_lightweight_process_diffs(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = pathlib.Path(tmp) / "stage3-copy"
            subprocess.run(
                [
                    sys.executable,
                    str(cig_script),
                    "demo",
                    "--fixture",
                    "python_minimal",
                    "--workspace",
                    str(temp_repo),
                ],
                check=True,
                cwd=repo_root,
            )

            config_path = temp_repo / ".zhanggong-impact-blueprint" / "config.json"
            task_id = "stage3-process"
            seed = "fn:src/app.py:login"
            subprocess.run(
                [
                    sys.executable,
                    str(cig_script),
                    "report",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(config_path),
                    "--task-id",
                    task_id,
                    "--seed",
                    seed,
                ],
                check=True,
                cwd=temp_repo,
            )

            app_path = temp_repo / "examples" / "python_minimal" / "src" / "app.py"
            original = app_path.read_text(encoding="utf-8")
            self.assertIn("def login(", original)
            updated = original.replace(
                "def login(user_name: str, password: str) -> dict:\n",
                "def audit_login_attempt(user_name: str) -> str:\n    return user_name.strip()\n\n\ndef login(user_name: str, password: str) -> dict:\n",
            ).replace(
                "    session_token = create_session(1)\n",
                "    audit_login_attempt(user_name)\n    session_token = create_session(1)\n",
            )
            app_path.write_text(updated, encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(cig_script),
                    "after-edit",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(config_path),
                    "--task-id",
                    task_id,
                    "--seed",
                    seed,
                    "--changed-file",
                    "src/app.py",
                ],
                check=True,
                cwd=temp_repo,
            )

            db_path = temp_repo / ".ai" / "codegraph" / "codegraph.db"
            self.assertTrue(db_path.exists())

            with closing(sqlite3.connect(db_path)) as conn:
                task_run_rows = conn.execute(
                    "SELECT command_name, status FROM task_runs WHERE task_id = ? ORDER BY created_at",
                    (task_id,),
                ).fetchall()
                self.assertGreaterEqual(len(task_run_rows), 2)
                self.assertIn(("report", "completed"), task_run_rows)
                self.assertIn(("after-edit", "completed"), task_run_rows)

                edit_round = conn.execute(
                    "SELECT changed_files_json, summary_json FROM edit_rounds WHERE task_id = ? ORDER BY round_index DESC LIMIT 1",
                    (task_id,),
                ).fetchone()
                self.assertIsNotNone(edit_round)
                changed_files = json.loads(edit_round[0])
                summary = json.loads(edit_round[1])
                self.assertEqual(changed_files, ["src/app.py"])
                self.assertIn("function_diffs", summary)
                self.assertIn("relation_diffs", summary)

                file_diff_rows = conn.execute(
                    "SELECT file_path, diff_kind FROM file_diffs WHERE edit_round_id = (SELECT edit_round_id FROM edit_rounds WHERE task_id = ? ORDER BY round_index DESC LIMIT 1)",
                    (task_id,),
                ).fetchall()
                self.assertIn(("src/app.py", "modified"), file_diff_rows)

                symbol_diff_rows = conn.execute(
                    "SELECT diff_kind, before_symbol, after_symbol FROM symbol_diffs WHERE edit_round_id = (SELECT edit_round_id FROM edit_rounds WHERE task_id = ? ORDER BY round_index DESC LIMIT 1)",
                    (task_id,),
                ).fetchall()
                self.assertIn(("added", None, "audit_login_attempt"), symbol_diff_rows)
                self.assertIn(("modified", "login", "login"), symbol_diff_rows)

                login_diff = summary["relation_diffs"]["fn:src/app.py:login"]
                self.assertIn("fn:src/app.py:audit_login_attempt", login_diff["callees_added"])


if __name__ == "__main__":
    unittest.main()

