import json
import importlib.util
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

from tests.test_stage11_workflow import build_repo, config_path, setup_repo, write_python_repo_with_dependencies, write_python_repo_with_two_tests, write_ts_repo
from tests.test_stage13_workflow import analyze_repo, recommend_tests
from tests.test_stage7_workflow import copy_single_skill_folder, run_json


def finish_repo(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *,
    changed_files: list[str] | None = None,
    test_scope: str | None = None,
    allow_fallback: bool = False,
    shadow_full: bool = False,
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
    if test_scope:
        command.extend(["--test-scope", test_scope])
    if allow_fallback:
        command.append("--allow-fallback")
    if shadow_full:
        command.append("--shadow-full")
    return run_json(command, cwd=repo_root)


def install_integration_pack(repo_cig: pathlib.Path, repo_root: pathlib.Path) -> dict:
    return run_json(
        [
            sys.executable,
            str(repo_cig),
            "install-integration-pack",
            "--workspace-root",
            str(repo_root),
            "--config",
            str(config_path(repo_root)),
        ],
        cwd=repo_root,
    )


def latest_jsonl_row(path: pathlib.Path) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[-1]


def write_shadow_repo(repo_root: pathlib.Path) -> None:
    write_python_repo_with_two_tests(repo_root)
    (repo_root / "tests" / "test_session.py").write_text(
        "import unittest\n\n"
        "class SessionTest(unittest.TestCase):\n"
        "    def test_session_expiry(self):\n"
        "        self.assertEqual('expired', 'active')\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )


def write_contract_repo(repo_root: pathlib.Path) -> None:
    write_ts_repo(
        repo_root,
        "contracts.ts",
        "const config = { get(key) { return key } };\n"
        "const ipcRenderer = { send(channel, payload) { return { channel, payload }; } };\n"
        "export function syncSession(userId) {\n"
        "  const baseUrl = process.env.API_URL;\n"
        "  const authMode = config.get('auth.mode');\n"
        "  ipcRenderer.send('auth:login', { userId, authMode });\n"
        "  const sql = \"select * from sessions where user_id = ?\";\n"
        "  return { baseUrl, authMode, sql };\n"
        "}\n",
    )


class Stage14WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = pathlib.Path(__file__).resolve().parents[1]
        cls.cig_script = cls.repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
        spec = importlib.util.spec_from_file_location("stage14_cig_module", cls.cig_script)
        if spec is None or spec.loader is None:
                raise RuntimeError("Unable to load ZG Impact Blueprint module for Stage 14 tests")
        cls.cig_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cig_module)
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

    def test_verification_budget_escalates_dependency_change_to_B4(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "budget-b4"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_dependencies(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            build_repo(repo_cig, repo_root)
            (repo_root / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")

            analyze_payload = analyze_repo(
                repo_cig,
                repo_root,
                seed="fn:src/app.py:login",
                changed_files=["requirements.txt"],
            )
            next_action = json.loads(pathlib.Path(analyze_payload["machine_outputs"]["next_action_path"]).read_text(encoding="utf-8"))

            self.assertEqual(next_action["verification_budget"], "B4")
            self.assertEqual(next_action["recommended_test_scope"], "full")
            self.assertIn("dependency_changed", next_action["budget_reason_codes"])

    def test_verification_budget_uses_B2_for_low_risk_direct_tests(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "budget-b2"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            next_action = json.loads(pathlib.Path(analyze_payload["machine_outputs"]["next_action_path"]).read_text(encoding="utf-8"))
            verification_policy = json.loads((repo_root / ".ai" / "codegraph" / "verification-policy.json").read_text(encoding="utf-8"))

            self.assertEqual(next_action["verification_budget"], "B2")
            self.assertEqual(next_action["recommended_test_scope"], "targeted")
            self.assertEqual(verification_policy["verification_policy"]["default_budget"], "B2")

    def test_shadow_full_records_missed_failure(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "shadow-full"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_shadow_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            app_path = repo_root / "src" / "app.py"
            app_path.write_text(
                app_path.read_text(encoding="utf-8").replace("'baseline'", "'shadow-pass'"),
                encoding="utf-8",
            )

            finish_payload = finish_repo(
                repo_cig,
                repo_root,
                changed_files=["src/app.py"],
                test_scope="targeted",
                shadow_full=True,
            )
            selection_quality = finish_payload["tests"]["selection_quality"]
            calibration_row = latest_jsonl_row(repo_root / ".ai" / "codegraph" / "calibration.jsonl")

            self.assertTrue(selection_quality["shadow_run"])
            self.assertTrue(selection_quality["targeted_passed"])
            self.assertFalse(selection_quality["shadow_passed"])
            self.assertFalse(selection_quality["safe"])
            self.assertTrue(selection_quality["missed_failures"])
            self.assertFalse(calibration_row["selection_quality"]["safe"])

    def test_history_ranker_prioritizes_previously_failed_related_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "history-ranker"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_shadow_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            history_path = repo_root / ".ai" / "codegraph" / "test-history.jsonl"
            history_path.write_text(
                json.dumps(
                    {
                        "changed_files": ["src/app.py"],
                        "changed_symbols": ["login"],
                        "recommended_tests": [],
                        "executed_commands": [],
                        "failed_tests": ["tests.test_session.SessionTest.test_session_expiry"],
                        "test_scope": "targeted",
                        "dependency_fingerprint_status": "unchanged",
                        "parser_trust": "medium",
                        "graph_trust": "high",
                        "budget": "B2",
                        "timestamp": "2026-04-19T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            payload = recommend_tests(repo_cig, repo_root, analyze_payload["task_id"])

            self.assertTrue(payload["recommended_tests"])
            self.assertIn("tests.test_session.SessionTest.test_session_expiry", " ".join(payload["recommended_tests"][0]["command"]))
            self.assertIn("history co-failure", payload["recommended_tests"][0]["ranking_explanation"])

    def test_install_integration_pack_creates_runtime_files(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "integration-pack"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            install_integration_pack(repo_cig, repo_root)

            self.assertTrue((repo_root / "AGENTS.md").exists())
            self.assertTrue((repo_root / ".ai" / "codegraph" / "runtime" / "SESSION_START.md").exists())
            self.assertTrue((repo_root / ".ai" / "codegraph" / "runtime" / "BEFORE_EDIT.md").exists())
            self.assertTrue((repo_root / ".ai" / "codegraph" / "runtime" / "AFTER_EDIT.md").exists())
            self.assertTrue((repo_root / ".ai" / "codegraph" / "runtime" / "BEFORE_STOP.md").exists())
            self.assertTrue((repo_root / ".ai" / "codegraph" / "pending-changes.jsonl").exists())

    def test_install_integration_pack_updates_agents_managed_block_without_overwriting_user_content(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "integration-pack-managed-block"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            agents_path = repo_root / "AGENTS.md"
            agents_path.write_text(
                "# User Notes\n\nKeep this section.\n\n<!-- CIG:START -->\nold block\n<!-- CIG:END -->\n",
                encoding="utf-8",
            )

            install_integration_pack(repo_cig, repo_root)
            content = agents_path.read_text(encoding="utf-8")

            self.assertIn("Keep this section.", content)
            self.assertIn("Adaptive Verification Orchestrator", content)
            self.assertEqual(content.count("<!-- CIG:START -->"), 1)
            self.assertEqual(content.count("<!-- CIG:END -->"), 1)

    def test_install_integration_pack_is_idempotent(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "integration-pack-idempotent"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            install_integration_pack(repo_cig, repo_root)
            first_agents = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
            install_integration_pack(repo_cig, repo_root)
            second_agents = (repo_root / "AGENTS.md").read_text(encoding="utf-8")

            self.assertEqual(first_agents, second_agents)
            self.assertEqual(second_agents.count("<!-- CIG:START -->"), 1)

    def test_after_edit_records_pending_change(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "pending-change"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            app_path = repo_root / "src" / "app.py"
            app_path.write_text(
                app_path.read_text(encoding="utf-8").replace("'baseline'", "'pending-change'"),
                encoding="utf-8",
            )

            finish_repo(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
            pending_row = latest_jsonl_row(repo_root / ".ai" / "codegraph" / "pending-changes.jsonl")

            self.assertEqual(pending_row["path"], "src/app.py")
            self.assertEqual(pending_row["source"], "finish")
            self.assertEqual(pending_row["status"], "pending")
            self.assertIn("timestamp", pending_row)

    def test_finish_records_budget_in_test_history(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "history-budget"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            app_path = repo_root / "src" / "app.py"
            app_path.write_text(
                app_path.read_text(encoding="utf-8").replace("'baseline'", "'history-budget'"),
                encoding="utf-8",
            )

            finish_payload = finish_repo(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
            history_row = latest_jsonl_row(repo_root / ".ai" / "codegraph" / "test-history.jsonl")

            self.assertEqual(history_row["budget"], finish_payload["tests"]["verification_budget"])
            self.assertEqual(history_row["test_scope"], finish_payload["tests"]["effective_test_scope"])

    def test_runtime_contract_detects_env_config_ipc_sql_nodes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "contract-graph"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_contract_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")

            build_repo(repo_cig, repo_root)
            db_path = repo_root / ".ai" / "codegraph" / "codegraph.db"
            with closing(sqlite3.connect(db_path)) as conn:
                node_kinds = {row[0] for row in conn.execute("SELECT DISTINCT kind FROM nodes").fetchall()}
                edge_types = {row[0] for row in conn.execute("SELECT DISTINCT edge_type FROM edges").fetchall()}

            self.assertIn("env_var", node_kinds)
            self.assertIn("config_key", node_kinds)
            self.assertIn("ipc_channel", node_kinds)
            self.assertIn("sql_table", node_kinds)
            self.assertIn("READS_ENV", edge_types)
            self.assertIn("READS_CONFIG", edge_types)
            self.assertIn("IPC_SENDS", edge_types)
            self.assertIn("QUERIES_TABLE", edge_types)

    def test_next_action_includes_budget_and_multidimensional_trust(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "next-action-budget"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            next_action = json.loads(pathlib.Path(analyze_payload["machine_outputs"]["next_action_path"]).read_text(encoding="utf-8"))

            self.assertEqual(next_action["verification_budget"], "B2")
            self.assertIn("trust", next_action)
            self.assertIn("overall", next_action["trust"])
            self.assertIn("recommended_test_scope", next_action)
            self.assertIn("budget_reason_codes", next_action)

    def test_skill_doc_mentions_verification_budget_shadow_full_and_runtime_integration_pack(self):
        skill_path = pathlib.Path(__file__).resolve().parents[1] / ".agents" / "skills" / "zhanggong-impact-blueprint" / "SKILL.md"
        skill_text = skill_path.read_text(encoding="utf-8")

        self.assertIn("verification budget", skill_text.lower())
        self.assertIn("--shadow-full", skill_text)
        self.assertIn("install-integration-pack", skill_text)


if __name__ == "__main__":
    unittest.main()

