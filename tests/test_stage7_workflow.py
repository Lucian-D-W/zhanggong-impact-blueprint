import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


def run_json(cmd: list[str], cwd: pathlib.Path) -> dict:
    return json.loads(subprocess.check_output(cmd, cwd=cwd, text=True))


def copy_single_skill_folder(single_folder_export: pathlib.Path, repo_root: pathlib.Path) -> pathlib.Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    skill_source = single_folder_export / "code-impact-guardian"
    skill_target = repo_root / ".agents" / "skills" / "code-impact-guardian"
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_source, skill_target)
    return skill_target / "cig.py"


def write_python_repo(repo_root: pathlib.Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "rules").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "src" / "app.py").write_text(
        "def login(user_name, password):\n"
        "    if not user_name or not password:\n"
        "        return {'ok': False, 'message': 'missing'}\n"
        "    return {'ok': True, 'message': 'baseline'}\n",
        encoding="utf-8",
    )
    (repo_root / "tests" / "test_app.py").write_text(
        "import unittest\n"
        "from src.app import login\n\n"
        "class LoginTest(unittest.TestCase):\n"
        "    def test_login(self):\n"
        "        self.assertTrue(login('demo', 'secret')['ok'])\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )
    (repo_root / "docs" / "rules" / "auth.md").write_text(
        "---\n"
        "id: py-auth\n"
        "governs:\n"
        "  - fn:src/app.py:login\n"
        "---\n\n"
        "Login requires both username and password.\n",
        encoding="utf-8",
    )


def write_tsjs_repo(repo_root: pathlib.Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "rules").mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        json.dumps(
            {
                "name": "stage7-tsjs-minimal",
                "private": True,
                "type": "module",
                "scripts": {"test:node-cli": "node --test"},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "cli.js").write_text(
        "export function runCommand(name) {\n"
        "  const DEMO_STAGE7_TRACK = 'baseline';\n"
        "  return `${DEMO_STAGE7_TRACK}:${name}`;\n"
        "}\n",
        encoding="utf-8",
    )
    (repo_root / "tests" / "cli.test.js").write_text(
        "import test from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "import { runCommand } from '../src/cli.js';\n\n"
        "test('runCommand returns a stable label', () => {\n"
        "  assert.match(runCommand('demo'), /^(baseline|edited):demo$/);\n"
        "});\n",
        encoding="utf-8",
    )
    (repo_root / "docs" / "rules" / "cli.md").write_text(
        "---\n"
        "id: tsjs-cli\n"
        "governs:\n"
        "  - fn:src/cli.js:runCommand\n"
        "---\n\n"
        "CLI command helpers must keep stable output formatting.\n",
        encoding="utf-8",
    )


def write_tsjs_sql_repo(repo_root: pathlib.Path) -> None:
    write_tsjs_repo(repo_root)
    (repo_root / "db" / "functions").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests" / "sql").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "dbClient.js").write_text(
        "export function createSession(userId) {\n"
        "  const sql = `select app_create_session('${userId}')`;\n"
        "  return sql;\n"
        "}\n",
        encoding="utf-8",
    )
    (repo_root / "tests" / "dbClient.test.js").write_text(
        "import test from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "import { createSession } from '../src/dbClient.js';\n\n"
        "test('createSession produces SQL for the stored procedure', () => {\n"
        "  assert.match(createSession('demo'), /app_create_session/);\n"
        "});\n",
        encoding="utf-8",
    )
    (repo_root / "db" / "functions" / "001_session.sql").write_text(
        "create or replace function app_touch_session(user_id text)\n"
        "returns text\n"
        "language plpgsql\n"
        "as $$\n"
        "begin\n"
        "  return user_id;\n"
        "end;\n"
        "$$;\n\n"
        "create or replace function app_create_session(user_id text)\n"
        "returns text\n"
        "language plpgsql\n"
        "as $$\n"
        "begin\n"
        "  perform app_touch_session(user_id);\n"
        "  return user_id;\n"
        "end;\n"
        "$$;\n",
        encoding="utf-8",
    )
    (repo_root / "tests" / "sql" / "session.sql").write_text(
        "select app_create_session('demo');\n",
        encoding="utf-8",
    )
    (repo_root / "docs" / "rules" / "db.md").write_text(
        "---\n"
        "id: session-sql\n"
        "governs:\n"
        "  - fn:db/functions/001_session.sql:app_create_session\n"
        "---\n\n"
        "Session creation SQL must remain stable and auditable.\n",
        encoding="utf-8",
    )


def write_generic_repo(repo_root: pathlib.Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "settings.workflow").write_text(
        "release_track=baseline\n",
        encoding="utf-8",
    )


class Stage7WorkflowTest(unittest.TestCase):
    def test_single_folder_setup_analyze_finish_for_python_tsjs_sql_and_generic(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "code-impact-guardian" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            single_export = pathlib.Path(tmp) / "single-folder-export"
            export_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(repo_root),
                    "--out",
                    str(single_export),
                    "--mode",
                    "single-folder",
                ],
                cwd=repo_root,
            )
            self.assertEqual(export_payload["mode"], "single-folder")
            self.assertTrue((single_export / "code-impact-guardian" / "cig.py").exists())
            self.assertFalse((single_export / ".ai").exists())
            self.assertFalse((single_export / "tests").exists())
            self.assertFalse((single_export / "examples").exists())

            python_repo = pathlib.Path(tmp) / "python-single-folder"
            python_cig = copy_single_skill_folder(single_export, python_repo)
            write_python_repo(python_repo)
            setup_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "setup",
                    "--workspace-root",
                    str(python_repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "python-basic",
                ],
                cwd=python_repo,
            )
            self.assertEqual(setup_payload["detect"]["detected_profile"], "python-basic")
            self.assertTrue((python_repo / "AGENTS.md").exists())
            self.assertTrue((python_repo / ".gitignore").exists())
            self.assertTrue((python_repo / ".code-impact-guardian" / "config.json").exists())
            self.assertTrue((python_repo / ".code-impact-guardian" / "schema.sql").exists())
            self.assertTrue((python_repo / "QUICKSTART.md").exists())
            self.assertTrue((python_repo / "TROUBLESHOOTING.md").exists())
            self.assertTrue((python_repo / "CONSUMER_GUIDE.md").exists())
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "analyze",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/app.py",
                ],
                cwd=python_repo,
            )
            self.assertTrue(analyze_payload["task_id"])
            self.assertEqual(analyze_payload["seed_selection"]["mode"], "auto-single")
            self.assertTrue((python_repo / ".ai" / "codegraph" / "last-task.json").exists())
            app_path = python_repo / "src" / "app.py"
            app_path.write_text(app_path.read_text(encoding="utf-8").replace("'baseline'", "'edited'"), encoding="utf-8")
            finish_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "finish",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/app.py",
                ],
                cwd=python_repo,
            )
            self.assertEqual(finish_payload["task_id"], analyze_payload["task_id"])
            self.assertEqual(finish_payload["seed"], analyze_payload["seed"])
            self.assertTrue((python_repo / ".ai" / "codegraph" / "handoff" / "latest.md").exists())

            tsjs_repo = pathlib.Path(tmp) / "tsjs-single-folder"
            tsjs_cig = copy_single_skill_folder(single_export, tsjs_repo)
            write_tsjs_repo(tsjs_repo)
            setup_payload = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "setup",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "node-cli",
                ],
                cwd=tsjs_repo,
            )
            self.assertEqual(setup_payload["detect"]["primary_adapter"], "tsjs")
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "analyze",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/cli.js",
                ],
                cwd=tsjs_repo,
            )
            self.assertEqual(analyze_payload["seed_selection"]["mode"], "auto-single")
            cli_path = tsjs_repo / "src" / "cli.js"
            cli_path.write_text(cli_path.read_text(encoding="utf-8").replace("'baseline'", "'edited'"), encoding="utf-8")
            finish_payload = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "finish",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/cli.js",
                ],
                cwd=tsjs_repo,
            )
            self.assertEqual(finish_payload["tests"]["status"], "passed")

            compound_repo = pathlib.Path(tmp) / "tsjs-sql-single-folder"
            compound_cig = copy_single_skill_folder(single_export, compound_repo)
            write_tsjs_sql_repo(compound_repo)
            setup_payload = run_json(
                [
                    sys.executable,
                    str(compound_cig),
                    "setup",
                    "--workspace-root",
                    str(compound_repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "node-cli",
                    "--with",
                    "sql-postgres",
                ],
                cwd=compound_repo,
            )
            self.assertIn("sql_postgres", setup_payload["detect"]["supplemental_adapters_detected"])
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(compound_cig),
                    "analyze",
                    "--workspace-root",
                    str(compound_repo),
                    "--config",
                    str(compound_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/dbClient.js",
                ],
                cwd=compound_repo,
            )
            self.assertIn("sql_postgres", analyze_payload["detect"]["supplemental_adapters_detected"])
            self.assertTrue(analyze_payload["report"]["report_path"])
            db_client_path = compound_repo / "src" / "dbClient.js"
            db_client_path.write_text(
                db_client_path.read_text(encoding="utf-8").replace("return sql;", "return `${sql} -- edited`;"),
                encoding="utf-8",
            )
            finish_payload = run_json(
                [
                    sys.executable,
                    str(compound_cig),
                    "finish",
                    "--workspace-root",
                    str(compound_repo),
                    "--config",
                    str(compound_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/dbClient.js",
                ],
                cwd=compound_repo,
            )
            self.assertEqual(finish_payload["tests"]["status"], "passed")
            status_payload = run_json(
                [
                    sys.executable,
                    str(compound_cig),
                    "status",
                    "--workspace-root",
                    str(compound_repo),
                    "--config",
                    str(compound_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=compound_repo,
            )
            self.assertIn("sql_postgres", status_payload["current"]["supplemental_adapters"])
            self.assertTrue(status_payload["latest_report_path"])
            self.assertTrue(status_payload["next_step"])

            generic_repo = pathlib.Path(tmp) / "generic-single-folder"
            generic_cig = copy_single_skill_folder(single_export, generic_repo)
            write_generic_repo(generic_repo)
            setup_payload = run_json(
                [
                    sys.executable,
                    str(generic_cig),
                    "setup",
                    "--workspace-root",
                    str(generic_repo),
                    "--project-root",
                    ".",
                ],
                cwd=generic_repo,
            )
            self.assertIn(setup_payload["detect"]["primary_adapter"], {"generic", "tsjs", "python"})
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(generic_cig),
                    "analyze",
                    "--workspace-root",
                    str(generic_repo),
                    "--config",
                    str(generic_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/settings.workflow",
                    "--allow-fallback",
                ],
                cwd=generic_repo,
            )
            self.assertTrue(analyze_payload["seed"].startswith("file:"))
            settings_path = generic_repo / "src" / "settings.workflow"
            settings_path.write_text("release_track=edited\n", encoding="utf-8")
            finish_payload = run_json(
                [
                    sys.executable,
                    str(generic_cig),
                    "finish",
                    "--workspace-root",
                    str(generic_repo),
                    "--config",
                    str(generic_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/settings.workflow",
                    "--allow-fallback",
                ],
                cwd=generic_repo,
            )
            self.assertEqual(finish_payload["seed"], analyze_payload["seed"])

    def test_status_handoff_and_structured_recovery_are_more_actionable(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "code-impact-guardian" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            single_export = pathlib.Path(tmp) / "single-folder-export"
            run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(repo_root),
                    "--out",
                    str(single_export),
                    "--mode",
                    "single-folder",
                ],
                cwd=repo_root,
            )
            repo = pathlib.Path(tmp) / "python-failure-repo"
            repo_cig = copy_single_skill_folder(single_export, repo)
            write_python_repo(repo)

            run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "setup",
                    "--workspace-root",
                    str(repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "python-basic",
                ],
                cwd=repo,
            )
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "analyze",
                    "--workspace-root",
                    str(repo),
                    "--config",
                    str(repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/app.py",
                ],
                cwd=repo,
            )
            config_path = repo / ".code-impact-guardian" / "config.json"
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            config_payload["python"]["test_command"] = ["python", "-c", "import sys; sys.exit(3)"]
            config_path.write_text(json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            app_path = repo / "src" / "app.py"
            app_path.write_text(app_path.read_text(encoding="utf-8").replace("'baseline'", "'edited'"), encoding="utf-8")

            finish_run = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "finish",
                    "--workspace-root",
                    str(repo),
                    "--config",
                    str(config_path),
                    "--changed-file",
                    "src/app.py",
                ],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(finish_run.returncode, 0)
            self.assertNotIn("Traceback", finish_run.stderr)

            last_error = json.loads((repo / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "TEST_COMMAND_FAILED")
            self.assertTrue(last_error["suggested_next_step"])

            status_payload = run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "status",
                    "--workspace-root",
                    str(repo),
                    "--config",
                    str(config_path),
                ],
                cwd=repo,
            )
            self.assertTrue(status_payload["has_unhandled_error"])
            self.assertTrue(status_payload["next_step"])
            self.assertEqual(status_payload["last_error"]["error_code"], "TEST_COMMAND_FAILED")

            handoff_text = (repo / ".ai" / "codegraph" / "handoff" / "latest.md").read_text(encoding="utf-8")
            self.assertIn("Current task", handoff_text)
            self.assertIn("Recent successful step", handoff_text)
            self.assertIn("Recent failed step", handoff_text)
            self.assertIn("Critical paths", handoff_text)
            self.assertIn("Next step", handoff_text)
            self.assertIn(analyze_payload["task_id"], handoff_text)


if __name__ == "__main__":
    unittest.main()
