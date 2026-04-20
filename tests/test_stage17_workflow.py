import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import warnings

from tests.test_stage11_workflow import build_repo, config_path, setup_repo, write_python_repo_with_two_tests
from tests.test_stage15_workflow import analyze_change, load_next_action, run_finish_raw
from tests.test_stage16_workflow import (
    break_login_behavior,
    report_json,
    setup_repo_with_options,
    write_ipc_repo,
    write_node_base,
    write_route_component_repo,
    write_sql_repo,
    write_ts_config_repo,
    write_ts_dynamic_env_repo,
)
from tests.test_stage7_workflow import copy_single_skill_folder, run_json


def run_cig(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *args: str,
    timeout: int = 10,
    warning_error: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if warning_error:
        command.extend(["-W", "error::ResourceWarning"])
    command.extend([str(repo_cig), *args])
    return subprocess.run(
        command,
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def run_cig_json(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *args: str,
    timeout: int = 10,
    warning_error: bool = False,
) -> tuple[dict, subprocess.CompletedProcess[str]]:
    result = run_cig(
        repo_cig,
        repo_root,
        *args,
        timeout=timeout,
        warning_error=warning_error,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Command failed ({' '.join(args)}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return json.loads(result.stdout), result


def write_many_ipc_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    pairs = [
        ("auth:login", "Login"),
        ("auth:logout", "Logout"),
        ("auth:refresh", "Refresh"),
        ("profile:load", "Profile"),
        ("settings:save", "Settings"),
    ]
    lines = [
        "const ipcRenderer = { send(channel, payload) { return { channel, payload }; } };",
        "const ipcMain = { handle(channel, handler) { return { channel, handler }; } };",
    ]
    for channel, label in pairs:
        lines.append(
            f"export function send{label}(payload) {{\n"
            f"  return ipcRenderer.send('{channel}', payload);\n"
            "}\n"
        )
        lines.append(
            f"export function handle{label}() {{\n"
            f"  return ipcMain.handle('{channel}', async () => ({{ ok: true }}));\n"
            "}\n"
        )
    (repo_root / "src" / "many_ipc.ts").write_text("\n".join(lines), encoding="utf-8")


def atlas_views_for_type(payload: dict, view_type: str) -> list[dict]:
    return [view for view in payload.get("atlas_views", []) if view.get("view_type") == view_type]


def loop_breaker_payload(repo_root: pathlib.Path) -> dict:
    return json.loads((repo_root / ".ai" / "codegraph" / "loop-breaker-report.json").read_text(encoding="utf-8"))


class Stage17WorkflowTest(unittest.TestCase):
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

    def test_stage16_loop_breaker_runs_without_sqlite_resource_warning(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "strict-loop-breaker"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            (repo_root / "src" / "app.py").write_text(
                "import os\n\n"
                "def login(user_name, password):\n"
                "    if not user_name or not password:\n"
                "        return {'ok': False, 'message': 'missing', 'env': os.getenv('API_URL')}\n"
                "    return {'ok': True, 'message': 'baseline', 'env': os.getenv('API_URL')}\n",
                encoding="utf-8",
            )
            with warnings.catch_warnings():
                warnings.simplefilter("error", ResourceWarning)
                run_cig_json(
                    repo_cig,
                    repo_root,
                    "analyze",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(config_path(repo_root)),
                    "--seed",
                    "fn:src/app.py:login",
                    "--changed-file",
                    "src/app.py",
                    warning_error=True,
                    timeout=20,
                )
                break_login_behavior(repo_root)
                for _ in range(4):
                    result = run_cig(
                        repo_cig,
                        repo_root,
                        "finish",
                        "--workspace-root",
                        str(repo_root),
                        "--config",
                        str(config_path(repo_root)),
                        "--changed-file",
                        "src/app.py",
                        "--test-scope",
                        "targeted",
                        warning_error=True,
                        timeout=20,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("unclosed database", result.stderr)
                    self.assertNotIn("ResourceWarning", result.stderr)
            loop_breaker = loop_breaker_payload(repo_root)
            self.assertIn("contract_chain", loop_breaker)
            self.assertTrue(loop_breaker["contract_chain"].get("env_vars"))

    def test_graph_queries_close_sqlite_connections_under_strict_warning_mode(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "strict-queries"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            with warnings.catch_warnings():
                warnings.simplefilter("error", ResourceWarning)
                commands = [
                    ("build", "--workspace-root", str(repo_root), "--config", str(config_path(repo_root))),
                    (
                        "analyze",
                        "--workspace-root",
                        str(repo_root),
                        "--config",
                        str(config_path(repo_root)),
                        "--seed",
                        "fn:src/app.py:login",
                        "--changed-file",
                        "src/app.py",
                    ),
                    ("seeds", "--workspace-root", str(repo_root), "--config", str(config_path(repo_root))),
                    (
                        "report",
                        "--workspace-root",
                        str(repo_root),
                        "--config",
                        str(config_path(repo_root)),
                        "--task-id",
                        "stage17-strict-report",
                        "--seed",
                        "fn:src/app.py:login",
                        "--changed-file",
                        "src/app.py",
                    ),
                    ("status", "--workspace-root", str(repo_root), "--config", str(config_path(repo_root))),
                ]
                for command in commands:
                    _, result = run_cig_json(
                        repo_cig,
                        repo_root,
                        *command,
                        warning_error=True,
                        timeout=20,
                    )
                    self.assertNotIn("unclosed database", result.stderr)
                    self.assertNotIn("ResourceWarning", result.stderr)

    def test_temp_workspace_cleanup_after_repeated_finish(self):
        parent = pathlib.Path(tempfile.mkdtemp())
        temp_root: pathlib.Path | None = None
        try:
            with tempfile.TemporaryDirectory(dir=parent) as tmp:
                temp_root = pathlib.Path(tmp)
                repo_root = temp_root / "cleanup-loop"
                repo_cig = copy_single_skill_folder(self.single_export, repo_root)
                write_python_repo_with_two_tests(repo_root)
                setup_repo(repo_cig, repo_root, profile="python-basic")
                analyze_change(
                    repo_cig,
                    repo_root,
                    seed="fn:src/app.py:login",
                    changed_files=["src/app.py"],
                )
                break_login_behavior(repo_root)
                for _ in range(3):
                    result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                    self.assertNotEqual(result.returncode, 0)
            self.assertIsNotNone(temp_root)
            self.assertFalse(temp_root.exists())
        finally:
            if parent.exists():
                parent.rmdir()

    def test_cli_commands_exit_cleanly_with_timeout(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            export_dir = pathlib.Path(tmp) / "exported"
            export_result = subprocess.run(
                [
                    sys.executable,
                    str(self.cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(self.repo_root),
                    "--out",
                    str(export_dir),
                    "--mode",
                    "single-folder",
                ],
                cwd=self.repo_root,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(export_result.returncode, 0, export_result.stderr)

            repo_root = pathlib.Path(tmp) / "cli-smoke"
            repo_cig = copy_single_skill_folder(export_dir, repo_root)
            write_python_repo_with_two_tests(repo_root)
            (repo_root / "README.md").write_text("# CLI Smoke\n", encoding="utf-8")

            smoke_commands = [
                (
                    "setup",
                    "--workspace-root",
                    str(repo_root),
                    "--project-root",
                    ".",
                    "--profile",
                    "python-basic",
                ),
                ("build", "--workspace-root", str(repo_root), "--config", str(config_path(repo_root))),
                (
                    "analyze",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(config_path(repo_root)),
                    "--seed",
                    "fn:src/app.py:login",
                    "--changed-file",
                    "src/app.py",
                ),
                ("status", "--workspace-root", str(repo_root), "--config", str(config_path(repo_root))),
                ("health", "--workspace-root", str(repo_root), "--config", str(config_path(repo_root))),
                ("classify-change", "--workspace-root", str(repo_root), "--changed-file", "src/app.py"),
                ("assess-mutation", "--workspace-root", str(repo_root), "--path", "AGENTS.md", "--action", "move"),
                ("loop-status", "--workspace-root", str(repo_root)),
                ("diagnose-loop", "--workspace-root", str(repo_root), "--changed-file", "src/app.py"),
                ("install-integration-pack", "--workspace-root", str(repo_root), "--config", str(config_path(repo_root))),
                ("finish", "--workspace-root", str(repo_root), "--config", str(config_path(repo_root)), "--changed-file", "src/app.py", "--test-scope", "targeted"),
            ]

            analyze_task_id = None
            for command in smoke_commands:
                result = subprocess.run(
                    [sys.executable, str(repo_cig), *command],
                    cwd=repo_root,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, f"{command}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
                self.assertNotIn("hanging", result.stderr.lower())
                if command[0] == "analyze":
                    analyze_task_id = json.loads(result.stdout)["task_id"]

            self.assertIsNotNone(analyze_task_id)
            recommend_result = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "recommend-tests",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(config_path(repo_root)),
                    "--task-id",
                    analyze_task_id,
                ],
                cwd=repo_root,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(recommend_result.returncode, 0, recommend_result.stderr)

    def test_atlas_views_include_bilateral_ipc_view(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "atlas-ipc"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ipc_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)

            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/ipc.ts:sendLogin",
                changed_files=["src/ipc.ts"],
            )
            report = report_json(payload)
            bilateral = atlas_views_for_type(report, "bilateral_contract")
            self.assertTrue(bilateral)
            self.assertIn("auth:login", json.dumps(bilateral[0], ensure_ascii=False))

    def test_atlas_views_include_page_flow_view(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "atlas-page"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_route_component_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)

            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/routes.tsx:SettingsPage",
                changed_files=["src/routes.tsx"],
            )
            report = report_json(payload)
            page_views = atlas_views_for_type(report, "page_flow")
            self.assertTrue(page_views)
            self.assertIn("/settings", json.dumps(page_views[0], ensure_ascii=False))

    def test_atlas_views_include_data_flow_view(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "atlas-data"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_sql_repo(repo_root, include_migration=True)
            setup_repo_with_options(repo_cig, repo_root, profile="node-cli", extras=["sql-postgres"])
            build_repo(repo_cig, repo_root)

            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/db.ts:updateUsers",
                changed_files=["src/db.ts"],
            )
            report = report_json(payload)
            data_views = atlas_views_for_type(report, "data_flow")
            self.assertTrue(data_views)
            self.assertIn("users", json.dumps(data_views[0], ensure_ascii=False))

    def test_atlas_views_include_config_surface_view(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "atlas-config"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ts_config_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)

            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/config.ts:readAuthMode",
                changed_files=["src/config.ts"],
            )
            report = report_json(payload)
            config_views = atlas_views_for_type(report, "config_surface")
            self.assertTrue(config_views)
            self.assertIn("auth.mode", json.dumps(config_views[0], ensure_ascii=False))

    def test_uncertainty_view_collects_depends_on_low_confidence_edges(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "atlas-uncertainty"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ts_dynamic_env_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)

            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/env.ts:readDynamicEnv",
                changed_files=["src/env.ts"],
            )
            report = report_json(payload)
            uncertainty_views = atlas_views_for_type(report, "uncertainty")
            self.assertTrue(uncertainty_views)
            self.assertIn("DEPENDS_ON", json.dumps(uncertainty_views[0], ensure_ascii=False))

    def test_atlas_summary_compresses_noisy_contracts_without_deleting_full_data(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "atlas-compression"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_many_ipc_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)

            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="file:src/many_ipc.ts",
                changed_files=["src/many_ipc.ts"],
            )
            report = report_json(payload)

            self.assertGreater(len(report.get("affected_contracts", [])), 3)
            self.assertIn("atlas_summary", report)
            self.assertGreater(report["atlas_summary"].get("omitted_count", 0), 0)
            self.assertTrue(report["atlas_summary"].get("full_contracts_path"))
            self.assertLessEqual(len(atlas_views_for_type(report, "bilateral_contract")), 3)

    def test_next_action_user_message_mentions_both_sides_for_ipc_or_event(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "next-action-bilateral"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ipc_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)

            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/ipc.ts:sendLogin",
                changed_files=["src/ipc.ts"],
            )
            next_action = load_next_action(payload)
            self.assertIn("both", next_action["user_message"].lower())
            self.assertTrue(next_action.get("atlas_views"))

    def test_next_action_does_not_emit_full_atlas_for_bypass_markdown(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "next-action-bypass"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            (repo_root / "docs" / "archive").mkdir(parents=True, exist_ok=True)
            (repo_root / "docs" / "archive" / "note.md").write_text("# Note\n", encoding="utf-8")
            setup_repo(repo_cig, repo_root, profile="python-basic")

            payload = analyze_change(repo_cig, repo_root, changed_files=["docs/archive/note.md"])
            next_action = load_next_action(payload)
            self.assertEqual(next_action["change_class"], "bypass")
            self.assertFalse(next_action.get("atlas_views"))

    def test_loop_breaker_presents_atlas_views_after_repeated_failure(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "loop-atlas-l1"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            (repo_root / "src" / "app.py").write_text(
                "import os\n\n"
                "def login(user_name, password):\n"
                "    if not user_name or not password:\n"
                "        return {'ok': False, 'message': 'missing', 'env': os.getenv('API_URL')}\n"
                "    return {'ok': True, 'message': 'baseline', 'env': os.getenv('API_URL')}\n",
                encoding="utf-8",
            )
            analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/app.py:login",
                changed_files=["src/app.py"],
            )
            break_login_behavior(repo_root)
            for _ in range(2):
                result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                self.assertNotEqual(result.returncode, 0)

            loop_breaker = loop_breaker_payload(repo_root)
            self.assertTrue(loop_breaker.get("loop_atlas_views"))

    def test_loop_breaker_includes_uncertainty_view_after_three_retries(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "loop-atlas-l2"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            (repo_root / "src" / "app.py").write_text(
                "import os\n\n"
                "def login(user_name, password):\n"
                "    if not user_name or not password:\n"
                "        return {'ok': False, 'message': 'missing', 'env': os.getenv('API_URL')}\n"
                "    return {'ok': True, 'message': 'baseline', 'env': os.getenv('API_URL')}\n",
                encoding="utf-8",
            )
            analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/app.py:login",
                changed_files=["src/app.py"],
            )
            break_login_behavior(repo_root)
            for _ in range(3):
                result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                self.assertNotEqual(result.returncode, 0)

            loop_breaker = loop_breaker_payload(repo_root)
            uncertainty_views = [view for view in loop_breaker.get("loop_atlas_views", []) if view.get("view_type") == "uncertainty"]
            self.assertTrue(uncertainty_views)

    def test_loop_breaker_tells_agent_to_stop_local_patching_after_four_retries(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "loop-atlas-l3"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            (repo_root / "src" / "app.py").write_text(
                "import os\n\n"
                "def login(user_name, password):\n"
                "    if not user_name or not password:\n"
                "        return {'ok': False, 'message': 'missing', 'env': os.getenv('API_URL')}\n"
                "    return {'ok': True, 'message': 'baseline', 'env': os.getenv('API_URL')}\n",
                encoding="utf-8",
            )
            analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/app.py:login",
                changed_files=["src/app.py"],
            )
            break_login_behavior(repo_root)
            for _ in range(4):
                result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                self.assertNotEqual(result.returncode, 0)

            loop_breaker = loop_breaker_payload(repo_root)
            self.assertTrue(loop_breaker.get("stop_local_patching_reason"))

    def test_release_check_passes_clean_skill_folder(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "release-check-clean"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            payload, _ = run_cig_json(
                repo_cig,
                repo_root,
                "release-check",
                "--workspace-root",
                str(repo_root),
                "--skill-only",
            )
            self.assertEqual(payload["status"], "pass")
            self.assertTrue(payload["safe_to_publish_skill_folder"])

    def test_release_check_flags_private_name_in_skill_folder(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "release-check-private"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            (repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "notes.txt").write_text(
                "Reference mainstone.md before release.\n",
                encoding="utf-8",
            )
            payload, _ = run_cig_json(
                repo_cig,
                repo_root,
                "release-check",
                "--workspace-root",
                str(repo_root),
                "--skill-only",
            )
            self.assertEqual(payload["status"], "fail")
            self.assertTrue(any(issue["kind"] == "private_name_or_path" for issue in payload["issues"]))

    def test_release_check_flags_absolute_temp_path(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "release-check-temp"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            (repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "temp-leak.txt").write_text(
                "Leaked temp path: /tmp/tmpabc123/session.log\n",
                encoding="utf-8",
            )
            payload, _ = run_cig_json(
                repo_cig,
                repo_root,
                "release-check",
                "--workspace-root",
                str(repo_root),
                "--skill-only",
            )
            self.assertEqual(payload["status"], "fail")
            self.assertTrue(any(issue["kind"] == "absolute_temp_path" for issue in payload["issues"]))

    def test_release_check_excludes_runtime_artifacts(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "release-check-runtime"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            runtime_dir = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / ".ai" / "codegraph" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "SESSION_START.md").write_text("runtime artifact\n", encoding="utf-8")
            payload, _ = run_cig_json(
                repo_cig,
                repo_root,
                "release-check",
                "--workspace-root",
                str(repo_root),
                "--skill-only",
            )
            self.assertEqual(payload["status"], "fail")
            self.assertTrue(any(issue["kind"] == "runtime_artifact" for issue in payload["issues"]))

    def test_skill_doc_defines_agent_atlas_reading_order(self):
        skill_text = (
            pathlib.Path(__file__).resolve().parents[1]
            / ".agents"
            / "skills"
            / "zhanggong-impact-blueprint"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Recommended reading order", skill_text)
        self.assertIn("atlas_views", skill_text)
        self.assertIn("loop_atlas_views", skill_text)


if __name__ == "__main__":
    unittest.main()

