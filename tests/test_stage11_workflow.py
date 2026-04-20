import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / ".agents" / "skills" / "zhanggong-impact-blueprint" / "scripts"))

from after_edit_update import parse_test_count
from tests.test_stage7_workflow import copy_single_skill_folder, run_json, write_generic_repo, write_python_repo


def copy_example(repo_root: pathlib.Path, example_name: str) -> None:
    source = pathlib.Path(__file__).resolve().parents[1] / "examples" / example_name
    shutil.copytree(source, repo_root, dirs_exist_ok=True)


def config_path(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / ".zhanggong-impact-blueprint" / "config.json"


def init_git_repo(repo_root: pathlib.Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, text=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo_root, check=True, text=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Codex"], cwd=repo_root, check=True, text=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True, text=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo_root, check=True, text=True, capture_output=True)


def controlled_stage11_tempdir() -> tempfile.TemporaryDirectory[str]:
    base_dir = pathlib.Path(tempfile.gettempdir()) / "stage11-workspaces"
    base_dir.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=base_dir, ignore_cleanup_errors=True)


def run_emitted_command(command: str, *, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell is None:
            raise unittest.SkipTest("PowerShell is required to verify emitted recovery commands")
        return subprocess.run(
            [shell, "-NoProfile", "-Command", command],
            cwd=cwd,
            text=True,
            capture_output=True,
        )
    return subprocess.run(
        ["sh", "-lc", command],
        cwd=cwd,
        text=True,
        capture_output=True,
    )


def setup_repo(repo_cig: pathlib.Path, repo_root: pathlib.Path, *, profile: str | None = None) -> dict:
    command = [
        sys.executable,
        str(repo_cig),
        "setup",
        "--workspace-root",
        str(repo_root),
        "--project-root",
        ".",
    ]
    if profile:
        command.extend(["--profile", profile])
    return run_json(command, cwd=repo_root)


def build_repo(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    changed_files: list[str] | None = None,
    *,
    full_rebuild: bool = False,
) -> dict:
    command = [
        sys.executable,
        str(repo_cig),
        "build",
        "--workspace-root",
        str(repo_root),
        "--config",
        str(config_path(repo_root)),
    ]
    for changed_file in changed_files or []:
        command.extend(["--changed-file", changed_file])
    if full_rebuild:
        command.append("--full-rebuild")
    return run_json(command, cwd=repo_root)


def seeds_payload(repo_cig: pathlib.Path, repo_root: pathlib.Path) -> dict:
    return run_json(
        [
            sys.executable,
            str(repo_cig),
            "seeds",
            "--workspace-root",
            str(repo_root),
            "--config",
            str(config_path(repo_root)),
        ],
        cwd=repo_root,
    )


def analyze_repo(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *,
    changed_files: list[str] | None = None,
    changed_lines: list[str] | None = None,
    allow_fallback: bool = False,
) -> dict:
    command = [
        sys.executable,
        str(repo_cig),
        "analyze",
        "--workspace-root",
        str(repo_root),
        "--config",
        str(config_path(repo_root)),
    ]
    for changed_file in changed_files or []:
        command.extend(["--changed-file", changed_file])
    for changed_line in changed_lines or []:
        command.extend(["--changed-line", changed_line])
    if allow_fallback:
        command.append("--allow-fallback")
    return run_json(command, cwd=repo_root)


def finish_repo(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *,
    changed_files: list[str] | None = None,
    allow_fallback: bool = False,
) -> dict:
    command = [
        sys.executable,
        str(repo_cig),
        "finish",
        "--workspace-root",
        str(repo_root),
        "--config",
        str(config_path(repo_root)),
    ]
    for changed_file in changed_files or []:
        command.extend(["--changed-file", changed_file])
    if allow_fallback:
        command.append("--allow-fallback")
    return run_json(command, cwd=repo_root)


def edge_set(repo_root: pathlib.Path, edge_type: str) -> set[tuple[str, str]]:
    db_path = repo_root / ".ai" / "codegraph" / "codegraph.db"
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT src_id, dst_id FROM edges WHERE edge_type = ?",
            (edge_type,),
        ).fetchall()
    return {(src_id, dst_id) for src_id, dst_id in rows}


def rule_node_attrs(repo_root: pathlib.Path) -> dict:
    db_path = repo_root / ".ai" / "codegraph" / "codegraph.db"
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT attrs_json FROM nodes WHERE kind = 'rule' ORDER BY node_id LIMIT 1"
        ).fetchone()
    return json.loads(row[0]) if row else {}


def write_python_repo_with_dependencies(repo_root: pathlib.Path) -> None:
    write_python_repo(repo_root)
    (repo_root / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")


def write_python_repo_with_two_tests(repo_root: pathlib.Path) -> None:
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
        "    def test_login_accepts_valid_credentials(self):\n"
        "        self.assertTrue(login('demo', 'secret')['ok'])\n\n"
        "    def test_login_rejects_missing_password(self):\n"
        "        self.assertFalse(login('demo', '')['ok'])\n\n"
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


def write_ts_repo(repo_root: pathlib.Path, file_name: str, source_text: str) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        json.dumps(
            {
                "name": "stage11-ts",
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
    (repo_root / "src" / file_name).write_text(source_text, encoding="utf-8")


def write_python_instance_repo(repo_root: pathlib.Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "rules").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "src" / "service.py").write_text(
        "class UserService:\n"
        "    def validate_token(self, token: str) -> bool:\n"
        "        return token == 'demo'\n\n"
        "def check_token(token: str) -> bool:\n"
        "    svc = UserService()\n"
        "    return svc.validate_token(token)\n",
        encoding="utf-8",
    )
    (repo_root / "tests" / "test_service.py").write_text(
        "import unittest\n"
        "from src.service import UserService, check_token\n\n"
        "class TokenFlowTest(unittest.TestCase):\n"
        "    def test_check_token(self):\n"
        "        self.assertTrue(check_token('demo'))\n\n"
        "    def test_validate_token_directly(self):\n"
        "        svc = UserService()\n"
        "        self.assertTrue(svc.validate_token('demo'))\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )
    (repo_root / "docs" / "rules" / "token.md").write_text(
        "---\n"
        "id: svc-token\n"
        "governs:\n"
        "  - fn:src/service.py:UserService.validate_token\n"
        "---\n\n"
        "Token validation must remain stable.\n",
        encoding="utf-8",
    )


class Stage11WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = pathlib.Path(__file__).resolve().parents[1]
        cls.cig_script = cls.repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
        cls.export_tmp = tempfile.TemporaryDirectory()
        cls.single_export = pathlib.Path(cls.export_tmp.name) / "single-folder-export"
        run_json(
            [
                sys.executable,
                str(cls.cig_script),
                "export-skill",
                "--workspace-root",
                str(cls.repo_root),
                "--out",
                str(cls.single_export),
                "--mode",
                "single-folder",
            ],
            cwd=cls.repo_root,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.export_tmp.cleanup()

    def test_dependency_file_changes_force_full_rebuild_and_lower_trust(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "dep-changed"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_dependencies(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            build_repo(repo_cig, repo_root)
            requirements_path = repo_root / "requirements.txt"
            requirements_path.write_text("requests==2.32.0\n", encoding="utf-8")

            payload = build_repo(repo_cig, repo_root, changed_files=["requirements.txt"])
            decision = payload["build_decision"]
            self.assertIn("DEPENDENCY_FINGERPRINT_CHANGED", decision["reason_codes"])
            self.assertEqual(decision["dependency_fingerprint_status"], "changed")
            self.assertNotEqual(decision["graph_trust"], "high")
            self.assertEqual(decision["build_mode"], "full")

    def test_missing_dependency_fingerprint_keeps_trust_below_high(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "dep-unknown"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_dependencies(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            build_repo(repo_cig, repo_root)
            manifest_path = repo_root / ".ai" / "codegraph" / "build-manifest.json"
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload.setdefault("meta", {}).pop("dependency_fingerprint", None)
            manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            payload = build_repo(repo_cig, repo_root)
            status = payload["build_decision"]["dependency_fingerprint_status"]
            self.assertIn(status, {"unknown", "changed"})
            self.assertNotEqual(payload["build_decision"]["graph_trust"], "high")

    def test_forced_full_rebuild_preserves_dependency_change_downgrade(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "dep-changed-full"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_dependencies(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            build_repo(repo_cig, repo_root)
            requirements_path = repo_root / "requirements.txt"
            requirements_path.write_text("requests==2.32.0\n", encoding="utf-8")

            payload = build_repo(
                repo_cig,
                repo_root,
                changed_files=["requirements.txt"],
                full_rebuild=True,
            )
            decision = payload["build_decision"]
            self.assertEqual(decision["build_mode"], "full")
            self.assertEqual(decision["dependency_fingerprint_status"], "changed")
            self.assertIn("DEPENDENCY_FINGERPRINT_CHANGED", decision["reason_codes"])
            self.assertIn("FORCED_FULL_REBUILD", decision["reason_codes"])
            self.assertNotEqual(decision["graph_trust"], "high")

    def test_forced_full_rebuild_preserves_dependency_unknown_downgrade(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "dep-unknown-full"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_dependencies(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            build_repo(repo_cig, repo_root)
            manifest_path = repo_root / ".ai" / "codegraph" / "build-manifest.json"
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload.setdefault("meta", {}).pop("dependency_fingerprint", None)
            manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            payload = build_repo(repo_cig, repo_root, full_rebuild=True)
            decision = payload["build_decision"]
            self.assertEqual(decision["build_mode"], "full")
            self.assertEqual(decision["dependency_fingerprint_status"], "unknown")
            self.assertIn("DEPENDENCY_FINGERPRINT_UNKNOWN", decision["reason_codes"])
            self.assertIn("FORCED_FULL_REBUILD", decision["reason_codes"])
            self.assertNotEqual(decision["graph_trust"], "high")

    def test_ts_type_literal_does_not_truncate_function_boundary(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "typed-boundary"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ts_repo(
                repo_root,
                "typed.ts",
                "export function typed(opts: { name: string }) {\n"
                "  return helper(opts.name);\n"
                "}\n\n"
                "export function helper(name: string) {\n"
                "  return name.trim();\n"
                "}\n",
            )
            setup_repo(repo_cig, repo_root, profile="node-cli")

            build_repo(repo_cig, repo_root)
            details = {item["node_id"]: item for item in seeds_payload(repo_cig, repo_root)["function_details"]}
            typed = details["fn:src/typed.ts:typed"]
            self.assertEqual(typed["end_line"], 3)
            self.assertGreaterEqual(typed["attrs"]["parser_confidence"], 0.8)
            self.assertIsNone(typed["attrs"].get("parser_warning"))
            self.assertIn(
                ("fn:src/typed.ts:typed", "fn:src/typed.ts:helper"),
                edge_set(repo_root, "CALLS"),
            )

    def test_regex_literal_braces_do_not_truncate_function_boundary(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "regex-boundary"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ts_repo(
                repo_root,
                "rx.ts",
                "export function rx() {\n"
                "  const r = /}/;\n"
                "  return helper('}');\n"
                "}\n\n"
                "export function helper(value: string) {\n"
                "  return value;\n"
                "}\n",
            )
            setup_repo(repo_cig, repo_root, profile="node-cli")

            build_repo(repo_cig, repo_root)
            details = {item["node_id"]: item for item in seeds_payload(repo_cig, repo_root)["function_details"]}
            rx = details["fn:src/rx.ts:rx"]
            self.assertEqual(rx["end_line"], 4)
            self.assertIn(
                ("fn:src/rx.ts:rx", "fn:src/rx.ts:helper"),
                edge_set(repo_root, "CALLS"),
            )

    def test_multiline_arrow_block_keeps_correct_boundary(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "multiline-arrow"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ts_repo(
                repo_root,
                "arrow.ts",
                "export const typed = (\n"
                "  value: string\n"
                ") => {\n"
                "  return helper(value);\n"
                "};\n\n"
                "export function helper(value: string) {\n"
                "  return value.trim();\n"
                "}\n",
            )
            setup_repo(repo_cig, repo_root, profile="node-cli")

            build_repo(repo_cig, repo_root)
            details = {item["node_id"]: item for item in seeds_payload(repo_cig, repo_root)["function_details"]}
            typed = details["fn:src/arrow.ts:typed"]
            self.assertEqual(typed["end_line"], 5)
            self.assertGreaterEqual(typed["attrs"]["parser_confidence"], 0.8)
            self.assertIsNone(typed["attrs"].get("parser_warning"))
            self.assertIn(
                ("fn:src/arrow.ts:typed", "fn:src/arrow.ts:helper"),
                edge_set(repo_root, "CALLS"),
            )

    def test_function_declaration_line_does_not_create_self_call(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "self-call"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ts_repo(
                repo_root,
                "next.ts",
                "export function next() {\n"
                "  return typed();\n"
                "}\n\n"
                "export function typed() {\n"
                "  return 'ok';\n"
                "}\n",
            )
            setup_repo(repo_cig, repo_root, profile="node-cli")

            build_repo(repo_cig, repo_root)
            calls = edge_set(repo_root, "CALLS")
            self.assertNotIn(("fn:src/next.ts:next", "fn:src/next.ts:next"), calls)
            self.assertIn(("fn:src/next.ts:next", "fn:src/next.ts:typed"), calls)

    def test_frontmatter_duplicate_governs_warns_and_merges(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "frontmatter-duplicate"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            copy_example(repo_root, "python_minimal")
            (repo_root / "docs" / "rules" / "auth-session.md").write_text(
                "---\n"
                "id: auth-rule\n"
                "governs:\n"
                "  - fn:src/app.py:login\n"
                "governs:\n"
                "  - fn:src/session.py:create_session\n"
                "---\n"
                "Rule body.\n",
                encoding="utf-8",
            )
            setup_repo(repo_cig, repo_root, profile="python-basic")

            payload = build_repo(repo_cig, repo_root)
            governs = edge_set(repo_root, "GOVERNS")
            self.assertIn(("rule:auth-rule", "fn:src/app.py:login"), governs)
            self.assertIn(("rule:auth-rule", "fn:src/session.py:create_session"), governs)
            self.assertTrue(any("FRONTMATTER_DUPLICATE_KEY" in item for item in payload["warnings"]))
            self.assertIn("FRONTMATTER_DUPLICATE_KEY", " ".join(rule_node_attrs(repo_root).get("frontmatter_warnings", [])))

    def test_python_unittest_output_parses_real_test_count(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "test-count-parsed"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            app_path = repo_root / "src" / "app.py"
            app_path.write_text(app_path.read_text(encoding="utf-8").replace("'baseline'", "'edited'"), encoding="utf-8")
            finish_payload = finish_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            self.assertEqual(finish_payload["tests"]["tests_run"], 2)
            self.assertEqual(finish_payload["tests"]["test_count_status"], "parsed")

    def test_mixed_error_labels_do_not_double_count(self):
        tests_run, status = parse_test_count("2 error\n2 errors", "python")
        self.assertEqual(tests_run, 2)
        self.assertEqual(status, "parsed")

    def test_unrecognized_test_output_reports_unknown_count(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "test-count-unknown"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_generic_repo(repo_root)
            setup_repo(repo_cig, repo_root)

            current_config = json.loads(config_path(repo_root).read_text(encoding="utf-8"))
            current_config["generic"]["test_command"] = [sys.executable, "-c", "print('generic ok')"]
            config_path(repo_root).write_text(json.dumps(current_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            analyze_repo(repo_cig, repo_root, changed_files=["src/settings.workflow"], allow_fallback=True)
            (repo_root / "src" / "settings.workflow").write_text("release_track=stage11\n", encoding="utf-8")
            finish_payload = finish_repo(repo_cig, repo_root, changed_files=["src/settings.workflow"], allow_fallback=True)
            self.assertIsNone(finish_payload["tests"]["tests_run"])
            self.assertEqual(finish_payload["tests"]["test_count_status"], "unknown")

    def test_context_missing_writes_machine_recovery_commands(self):
        with controlled_stage11_tempdir() as tmp:
            repo_root = pathlib.Path(tmp) / "context $missing space"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo(repo_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "analyze",
                    "--workspace-root",
                    str(repo_root),
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            last_error = json.loads((repo_root / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "CONTEXT_MISSING")
            quoted_workspace_root = f"'{repo_root}'"
            self.assertEqual(
                last_error["recovery_commands"],
                [
                    f"python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root {quoted_workspace_root} --allow-fallback",
                    f"python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root {quoted_workspace_root} --changed-file <relative-path>",
                    f"python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root {quoted_workspace_root} --patch-file <patch-file>",
                    f'git -C {quoted_workspace_root} init',
                ],
            )
            self.assertFalse((repo_root / ".git").exists())
            init_result = run_emitted_command(last_error["recovery_commands"][-1], cwd=repo_root.parent)
            self.assertEqual(init_result.returncode, 0, init_result.stderr or init_result.stdout)
            self.assertTrue((repo_root / ".git").exists())
            self.assertFalse((repo_root.parent / ".git").exists())

    def test_delete_only_working_tree_change_infers_context(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "delete-only-context"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo(repo_root)
            init_git_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            (repo_root / "src" / "app.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "analyze",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(config_path(repo_root)),
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("CONTEXT_MISSING", result.stderr)
            context_resolution = json.loads((repo_root / ".ai" / "codegraph" / "context-resolution.json").read_text(encoding="utf-8"))
            self.assertIn("src/app.py", context_resolution["changed_files"])
            self.assertIn("src/app.py", context_resolution["effective_changed_files"])
            last_error = json.loads((repo_root / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "SEED_SELECTION_REQUIRED")

    def test_non_runtime_analyze_with_null_seed_does_not_break_followup_code_analyze(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "null-seed-followup"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo(repo_root)
            (repo_root / "notes.md").write_text("working note\n", encoding="utf-8")
            setup_repo(repo_cig, repo_root, profile="python-basic")
            build_repo(repo_cig, repo_root)

            note_payload = analyze_repo(repo_cig, repo_root, changed_files=["notes.md"])
            self.assertIsNone(note_payload["seed"])
            last_task = json.loads((repo_root / ".ai" / "codegraph" / "last-task.json").read_text(encoding="utf-8"))
            self.assertIsNone(last_task["seed"])

            followup_run = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "analyze",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(config_path(repo_root)),
                    "--changed-file",
                    "src/app.py",
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
            )
            self.assertEqual(followup_run.returncode, 0, followup_run.stderr or followup_run.stdout)
            followup_payload = json.loads(followup_run.stdout)
            self.assertEqual(followup_payload["changed_files"], ["src/app.py"])
            self.assertEqual(followup_payload["seed"], "fn:src/app.py:login")

    def test_python_instance_method_calls_create_call_and_cover_edges(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "instance-method"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_instance_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            build_repo(repo_cig, repo_root)
            calls = edge_set(repo_root, "CALLS")
            covers = edge_set(repo_root, "COVERS")
            self.assertIn(
                ("fn:src/service.py:check_token", "fn:src/service.py:UserService.validate_token"),
                calls,
            )
            self.assertIn(
                (
                    "test:tests/test_service.py:TokenFlowTest.test_validate_token_directly",
                    "fn:src/service.py:UserService.validate_token",
                ),
                covers,
            )

    def test_health_command_reports_read_only_recovery_state(self):
        with controlled_stage11_tempdir() as tmp:
            repo_root = pathlib.Path(tmp) / "health $ state"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)

            payload = run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "health",
                    "--workspace-root",
                    str(repo_root),
                ],
                cwd=repo_root,
            )
            self.assertFalse(payload["ready"])
            self.assertIn("config_missing", payload["issues"])
            quoted_workspace_root = f"'{repo_root}'"
            self.assertEqual(
                payload["fix_commands"],
                [
                    f"python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root {quoted_workspace_root} --project-root .",
                    f"python .agents/skills/zhanggong-impact-blueprint/cig.py build --workspace-root {quoted_workspace_root} --full-rebuild",
                ],
            )
            self.assertEqual(
                payload["next_command"],
                f"python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root {quoted_workspace_root} --project-root .",
            )
            self.assertEqual(payload["graph_trust"], "unknown")
            self.assertEqual(payload["dependency_fingerprint_status"], "unknown")
            self.assertEqual(payload["last_task_phase"], "none")
            self.assertFalse(payload["needs_finish"])
            self.assertFalse((repo_root / ".zhanggong-impact-blueprint" / "config.json").exists())
            setup_result = run_emitted_command(payload["next_command"], cwd=repo_root)
            self.assertEqual(setup_result.returncode, 0, setup_result.stderr or setup_result.stdout)
            self.assertTrue((repo_root / ".zhanggong-impact-blueprint" / "config.json").exists())
            self.assertFalse((repo_root.parent / ".zhanggong-impact-blueprint" / "config.json").exists())

    def test_build_lock_surfaces_recovery_commands(self):
        with controlled_stage11_tempdir() as tmp:
            repo_root = pathlib.Path(tmp) / "build $ lock"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            lock_path = repo_root / ".ai" / "codegraph" / "build.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text("busy\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "build",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(config_path(repo_root)),
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BUILD_LOCKED", result.stderr)
            last_error = json.loads((repo_root / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "BUILD_LOCKED")
            quoted_workspace_root = f"'{repo_root}'"
            quoted_lock_path = f"'{repo_root / '.ai' / 'codegraph' / 'build.lock'}'"
            self.assertEqual(
                last_error["recovery_commands"],
                [
                    f"python .agents/skills/zhanggong-impact-blueprint/cig.py status --workspace-root {quoted_workspace_root}",
                    f"rm {quoted_lock_path}",
                ],
            )
            remove_result = run_emitted_command(last_error["recovery_commands"][-1], cwd=repo_root.parent)
            self.assertEqual(remove_result.returncode, 0, remove_result.stderr or remove_result.stdout)
            self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()

