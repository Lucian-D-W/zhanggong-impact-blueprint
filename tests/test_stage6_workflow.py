import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


def run_json(cmd: list[str], cwd: pathlib.Path) -> dict:
    return json.loads(subprocess.check_output(cmd, cwd=cwd, text=True))


def copy_package_contents(package_root: pathlib.Path, repo_root: pathlib.Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    for child in package_root.iterdir():
        destination = repo_root / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def write_minimal_python_repo(repo_root: pathlib.Path) -> None:
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


def write_minimal_tsjs_repo(repo_root: pathlib.Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "rules").mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        json.dumps(
            {
                "name": "stage6-tsjs-minimal",
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
        "  const DEMO_STAGE6_TRACK = \"baseline\";\n"
        "  return `${DEMO_STAGE6_TRACK}:${name}`;\n"
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


class Stage6WorkflowTest(unittest.TestCase):
    def test_export_skill_and_skill_only_python_tsjs_repos_work(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            export_root = pathlib.Path(tmp) / "exported-skill"
            export_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(repo_root),
                    "--out",
                    str(export_root),
                ],
                cwd=repo_root,
            )
            self.assertTrue((export_root / "AGENTS.template.md").exists())
            self.assertTrue((export_root / "QUICKSTART.md").exists())
            self.assertTrue((export_root / "TROUBLESHOOTING.md").exists())
            self.assertTrue((export_root / ".zhanggong-impact-blueprint" / "config.template.json").exists())
            self.assertTrue((export_root / ".zhanggong-impact-blueprint" / "schema.sql").exists())
            self.assertTrue((export_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py").exists())
            for forbidden in (".git", ".ai", "tests", "examples", "dist", "__pycache__"):
                self.assertFalse((export_root / forbidden).exists(), f"{forbidden} must not be exported")
            self.assertEqual(export_payload["status"], "exported")

            python_repo = pathlib.Path(tmp) / "python-skill-only"
            copy_package_contents(export_root, python_repo)
            write_minimal_python_repo(python_repo)
            python_cig = python_repo / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

            init_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "init",
                    "--workspace-root",
                    str(python_repo),
                    "--profile",
                    "python-basic",
                    "--project-root",
                    ".",
                    "--write-agents-md",
                    "--write-gitignore",
                ],
                cwd=python_repo,
            )
            self.assertEqual(init_payload["project_profile"], "python-basic")
            self.assertTrue((python_repo / "AGENTS.md").exists())
            self.assertTrue((python_repo / ".gitignore").exists())

            subprocess.run(
                [
                    sys.executable,
                    str(python_cig),
                    "doctor",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=python_repo,
                check=True,
            )
            detect_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "detect",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=python_repo,
            )
            self.assertEqual(detect_payload["primary_adapter"], "python")
            run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "build",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=python_repo,
            )
            seeds_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "seeds",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=python_repo,
            )
            login_seed = next(item for item in seeds_payload["function_details"] if item["symbol"] == "login")
            run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "report",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--task-id",
                    "stage6-python",
                    "--seed",
                    login_seed["node_id"],
                ],
                cwd=python_repo,
            )
            app_path = python_repo / "src" / "app.py"
            app_path.write_text(app_path.read_text(encoding="utf-8").replace("'baseline'", "'edited'"), encoding="utf-8")
            run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "after-edit",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--task-id",
                    "stage6-python",
                    "--seed",
                    login_seed["node_id"],
                    "--changed-file",
                    "src/app.py",
                ],
                cwd=python_repo,
            )
            status_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "status",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=python_repo,
            )
            self.assertTrue(status_payload["latest_report_path"])
            self.assertTrue(status_payload["latest_test_results_path"])
            self.assertGreater(status_payload["available_seed_count"], 0)
            self.assertTrue((python_repo / ".ai" / "codegraph" / "handoff" / "latest.md").exists())

            tsjs_repo = pathlib.Path(tmp) / "tsjs-skill-only"
            copy_package_contents(export_root, tsjs_repo)
            write_minimal_tsjs_repo(tsjs_repo)
            tsjs_cig = tsjs_repo / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

            init_payload = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "init",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--profile",
                    "node-cli",
                    "--project-root",
                    ".",
                    "--write-agents-md",
                    "--write-gitignore",
                ],
                cwd=tsjs_repo,
            )
            self.assertEqual(init_payload["project_profile"], "node-cli")
            subprocess.run(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "doctor",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=tsjs_repo,
                check=True,
            )
            detect_payload = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "detect",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=tsjs_repo,
            )
            self.assertEqual(detect_payload["primary_adapter"], "tsjs")
            run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "build",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=tsjs_repo,
            )
            seeds_payload = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "seeds",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=tsjs_repo,
            )
            run_seed = next(item for item in seeds_payload["function_details"] if item["symbol"] == "runCommand")
            run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "report",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--task-id",
                    "stage6-tsjs",
                    "--seed",
                    run_seed["node_id"],
                ],
                cwd=tsjs_repo,
            )
            cli_path = tsjs_repo / "src" / "cli.js"
            cli_path.write_text(
                cli_path.read_text(encoding="utf-8").replace('"baseline"', '"edited"'),
                encoding="utf-8",
            )
            run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "after-edit",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--task-id",
                    "stage6-tsjs",
                    "--seed",
                    run_seed["node_id"],
                    "--changed-file",
                    "src/cli.js",
                ],
                cwd=tsjs_repo,
            )
            status_payload = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "status",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=tsjs_repo,
            )
            self.assertEqual(status_payload["current"]["project_profile"], "node-cli")
            self.assertTrue((tsjs_repo / ".ai" / "codegraph" / "logs" / "events.jsonl").exists())
            self.assertTrue((tsjs_repo / ".ai" / "codegraph" / "handoff" / "latest.md").exists())

    def test_structured_error_logging_status_and_recovery_artifacts(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            export_root = pathlib.Path(tmp) / "exported-skill"
            run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(repo_root),
                    "--out",
                    str(export_root),
                ],
                cwd=repo_root,
            )

            missing_config_repo = pathlib.Path(tmp) / "missing-config"
            copy_package_contents(export_root, missing_config_repo)
            missing_cig = missing_config_repo / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
            build_run = subprocess.run(
                [
                    sys.executable,
                    str(missing_cig),
                    "build",
                    "--workspace-root",
                    str(missing_config_repo),
                    "--config",
                    str(missing_config_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=missing_config_repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(build_run.returncode, 0)
            self.assertNotIn("Traceback", build_run.stderr)
            last_error = json.loads((missing_config_repo / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "CONFIG_MISSING")

            invalid_profile_repo = pathlib.Path(tmp) / "invalid-profile"
            copy_package_contents(export_root, invalid_profile_repo)
            invalid_cig = invalid_profile_repo / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
            init_run = subprocess.run(
                [
                    sys.executable,
                    str(invalid_cig),
                    "init",
                    "--workspace-root",
                    str(invalid_profile_repo),
                    "--profile",
                    "does-not-exist",
                ],
                cwd=invalid_profile_repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(init_run.returncode, 0)
            last_error = json.loads((invalid_profile_repo / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "INVALID_PROFILE")

            sql_missing_repo = pathlib.Path(tmp) / "sql-missing"
            copy_package_contents(export_root, sql_missing_repo)
            write_minimal_tsjs_repo(sql_missing_repo)
            sql_missing_cig = sql_missing_repo / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
            run_json(
                [
                    sys.executable,
                    str(sql_missing_cig),
                    "init",
                    "--workspace-root",
                    str(sql_missing_repo),
                    "--profile",
                    "node-cli",
                    "--project-root",
                    ".",
                    "--with",
                    "sql-postgres",
                ],
                cwd=sql_missing_repo,
            )
            doctor_run = subprocess.run(
                [
                    sys.executable,
                    str(sql_missing_cig),
                    "doctor",
                    "--workspace-root",
                    str(sql_missing_repo),
                    "--config",
                    str(sql_missing_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=sql_missing_repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(doctor_run.returncode, 0)
            last_error = json.loads((sql_missing_repo / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "SUPPLEMENTAL_ADAPTER_MISSING")

            bad_test_repo = pathlib.Path(tmp) / "bad-test"
            copy_package_contents(export_root, bad_test_repo)
            write_minimal_python_repo(bad_test_repo)
            bad_test_cig = bad_test_repo / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
            run_json(
                [
                    sys.executable,
                    str(bad_test_cig),
                    "init",
                    "--workspace-root",
                    str(bad_test_repo),
                    "--profile",
                    "python-basic",
                    "--project-root",
                    ".",
                ],
                cwd=bad_test_repo,
            )
            config_path = bad_test_repo / ".zhanggong-impact-blueprint" / "config.json"
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            config_payload["python"]["test_command"] = ["python", "-c", "import sys; sys.exit(3)"]
            config_path.write_text(json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            run_json(
                [
                    sys.executable,
                    str(bad_test_cig),
                    "build",
                    "--workspace-root",
                    str(bad_test_repo),
                    "--config",
                    str(config_path),
                ],
                cwd=bad_test_repo,
            )
            seeds_payload = run_json(
                [
                    sys.executable,
                    str(bad_test_cig),
                    "seeds",
                    "--workspace-root",
                    str(bad_test_repo),
                    "--config",
                    str(config_path),
                ],
                cwd=bad_test_repo,
            )
            login_seed = next(item for item in seeds_payload["function_details"] if item["symbol"] == "login")
            run_json(
                [
                    sys.executable,
                    str(bad_test_cig),
                    "report",
                    "--workspace-root",
                    str(bad_test_repo),
                    "--config",
                    str(config_path),
                    "--task-id",
                    "stage6-bad-test",
                    "--seed",
                    login_seed["node_id"],
                ],
                cwd=bad_test_repo,
            )
            (bad_test_repo / "src" / "app.py").write_text(
                (bad_test_repo / "src" / "app.py").read_text(encoding="utf-8").replace("'baseline'", "'edited'"),
                encoding="utf-8",
            )
            after_run = subprocess.run(
                [
                    sys.executable,
                    str(bad_test_cig),
                    "after-edit",
                    "--workspace-root",
                    str(bad_test_repo),
                    "--config",
                    str(config_path),
                    "--task-id",
                    "stage6-bad-test",
                    "--seed",
                    login_seed["node_id"],
                    "--changed-file",
                    "src/app.py",
                ],
                cwd=bad_test_repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(after_run.returncode, 0)
            self.assertNotIn("Traceback", after_run.stderr)
            last_error = json.loads((bad_test_repo / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "TEST_COMMAND_FAILED")
            self.assertTrue(last_error["retryable"])

            status_payload = run_json(
                [
                    sys.executable,
                    str(bad_test_cig),
                    "status",
                    "--workspace-root",
                    str(bad_test_repo),
                    "--config",
                    str(config_path),
                ],
                cwd=bad_test_repo,
            )
            self.assertTrue(status_payload["has_unhandled_error"])
            self.assertIn("TEST_COMMAND_FAILED", status_payload["last_error"]["error_code"])
            handoff_text = (bad_test_repo / ".ai" / "codegraph" / "handoff" / "latest.md").read_text(encoding="utf-8")
            self.assertIn("Next step", handoff_text)
            self.assertIn("TEST_COMMAND_FAILED", handoff_text)


if __name__ == "__main__":
    unittest.main()

