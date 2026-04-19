import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests.test_stage11_workflow import config_path, setup_repo, write_python_repo_with_dependencies, write_python_repo_with_two_tests
from tests.test_stage7_workflow import copy_single_skill_folder, run_json


def analyze_change(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *,
    seed: str | None = None,
    changed_files: list[str] | None = None,
    allow_fallback: bool = False,
    escalation_level: str | None = None,
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
    if seed:
        command.extend(["--seed", seed])
    for changed_file in changed_files or []:
        command.extend(["--changed-file", changed_file])
    if allow_fallback:
        command.append("--allow-fallback")
    if escalation_level:
        command.extend(["--escalation-level", escalation_level])
    return run_json(command, cwd=repo_root)


def classify_change(repo_cig: pathlib.Path, repo_root: pathlib.Path, *, changed_files: list[str]) -> dict:
    command = [
        sys.executable,
        str(repo_cig),
        "classify-change",
        "--workspace-root",
        str(repo_root),
    ]
    for changed_file in changed_files:
        command.extend(["--changed-file", changed_file])
    return run_json(command, cwd=repo_root)


def loop_status(repo_cig: pathlib.Path, repo_root: pathlib.Path) -> dict:
    return run_json(
        [
            sys.executable,
            str(repo_cig),
            "loop-status",
            "--workspace-root",
            str(repo_root),
        ],
        cwd=repo_root,
    )


def diagnose_loop(repo_cig: pathlib.Path, repo_root: pathlib.Path, *, changed_files: list[str]) -> dict:
    command = [
        sys.executable,
        str(repo_cig),
        "diagnose-loop",
        "--workspace-root",
        str(repo_root),
    ]
    for changed_file in changed_files:
        command.extend(["--changed-file", changed_file])
    return run_json(command, cwd=repo_root)


def run_finish_raw(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *,
    changed_files: list[str] | None = None,
    test_scope: str | None = None,
) -> subprocess.CompletedProcess[str]:
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
    return subprocess.run(
        command,
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def load_next_action(analyze_payload: dict) -> dict:
    return json.loads(pathlib.Path(analyze_payload["machine_outputs"]["next_action_path"]).read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_jsonl_rows(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ensure_plain_docs(repo_root: pathlib.Path) -> None:
    (repo_root / "docs" / "archive").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "archive" / "note.md").write_text(
        "# Archive Note\n\nThis is a historical note.\n",
        encoding="utf-8",
    )
    (repo_root / "README.md").write_text(
        "# Demo Repo\n\nThis README only explains the demo workspace.\n",
        encoding="utf-8",
    )


def break_login_behavior(repo_root: pathlib.Path) -> None:
    (repo_root / "src" / "app.py").write_text(
        "def login(user_name, password):\n"
        "    return {'ok': False, 'message': 'broken'}\n",
        encoding="utf-8",
    )


class Stage15WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = pathlib.Path(__file__).resolve().parents[1]
        cls.cig_script = cls.repo_root / ".agents" / "skills" / "code-impact-guardian" / "cig.py"
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

    def test_docs_only_markdown_gets_B0_and_does_not_escalate_for_no_direct_tests(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "docs-b0"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            ensure_plain_docs(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_change(repo_cig, repo_root, changed_files=["docs/archive/note.md"])
            next_action = load_next_action(analyze_payload)

            self.assertEqual(next_action["change_class"], "bypass")
            self.assertEqual(next_action["verification_budget"], "B0")
            self.assertEqual(next_action["recommended_test_scope"], "none")
            self.assertNotIn("no_direct_tests", next_action["budget_reason_codes"])

    def test_rule_markdown_is_guarded_not_bypassed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "rule-guarded"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_change(repo_cig, repo_root, changed_files=["docs/rules/auth.md"])
            next_action = load_next_action(analyze_payload)

            self.assertNotEqual(next_action["change_class"], "bypass")
            self.assertEqual(next_action["flow_level"], "full_guardian")
            self.assertIn(next_action["verification_budget"], {"B2", "B3", "B4"})

    def test_skill_doc_command_semantics_are_guarded(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "skill-guarded"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            payload = classify_change(
                repo_cig,
                repo_root,
                changed_files=[".agents/skills/code-impact-guardian/SKILL.md"],
            )

            self.assertEqual(payload["change_class"], "guarded")
            self.assertNotEqual(payload["flow_level"], "skip")
            self.assertNotEqual(payload["verification_budget"], "B0")

    def test_plain_readme_copy_edit_is_lightweight(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "readme-lightweight"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            ensure_plain_docs(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            payload = classify_change(repo_cig, repo_root, changed_files=["README.md"])

            self.assertEqual(payload["change_class"], "lightweight")
            self.assertEqual(payload["verification_budget"], "B1")
            self.assertEqual(payload["recommended_test_scope"], "none")

    def test_mixed_docs_and_source_uses_heaviest_class(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "mixed-change"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            ensure_plain_docs(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            payload = classify_change(
                repo_cig,
                repo_root,
                changed_files=["docs/archive/note.md", "src/app.py"],
            )

            self.assertEqual(payload["change_class"], "mixed")
            self.assertEqual(payload["flow_level"], "full_guardian")
            self.assertEqual(payload["verification_budget"], "B2")

    def test_custom_bypass_globs_are_respected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "custom-bypass"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            config = read_json(config_path(repo_root))
            config.setdefault("flow_policy", {}).setdefault("bypass_globs", []).append("notes/**")
            write_json(config_path(repo_root), config)
            (repo_root / "notes").mkdir(parents=True, exist_ok=True)
            (repo_root / "notes" / "meeting.md").write_text("Meeting note.\n", encoding="utf-8")

            payload = classify_change(repo_cig, repo_root, changed_files=["notes/meeting.md"])

            self.assertEqual(payload["change_class"], "bypass")

    def test_dependency_file_overrides_bypass_and_becomes_B4(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "dependency-overrides"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_dependencies(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            config = read_json(config_path(repo_root))
            config.setdefault("flow_policy", {})["bypass_globs"] = ["**/*"]
            write_json(config_path(repo_root), config)

            payload = classify_change(repo_cig, repo_root, changed_files=["requirements.txt"])

            self.assertEqual(payload["change_class"], "risk_sensitive")
            self.assertEqual(payload["verification_budget"], "B4")

    def test_failed_finish_records_repair_attempt(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "repair-attempt-recorded"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            analyze_change(repo_cig, repo_root, changed_files=["src/app.py"])
            break_login_behavior(repo_root)

            result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
            rows = latest_jsonl_rows(repo_root / ".ai" / "codegraph" / "repair-attempts.jsonl")

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["tests_passed"])
            self.assertEqual(rows[0]["error_code"], "TEST_COMMAND_FAILED")
            self.assertEqual(rows[0]["chain_reveal_level"], "L0")

    def test_repeated_failure_escalates_from_L0_to_L1_to_L2_to_L3(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "repair-escalates"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            analyze_change(repo_cig, repo_root, changed_files=["src/app.py"])
            break_login_behavior(repo_root)

            observed = []
            for _ in range(4):
                result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                self.assertNotEqual(result.returncode, 0)
                observed.append(loop_status(repo_cig, repo_root))

            self.assertEqual([item["repeat_count"] for item in observed], [1, 2, 3, 4])
            self.assertEqual(
                [item["recommended_escalation"] for item in observed],
                ["L0", "L1", "L2", "L3"],
            )

    def test_loop_breaker_report_generated_after_three_retries(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "loop-breaker"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            analyze_change(repo_cig, repo_root, changed_files=["src/app.py"])
            break_login_behavior(repo_root)

            for _ in range(4):
                result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                self.assertNotEqual(result.returncode, 0)

            analyze_payload = analyze_change(repo_cig, repo_root, changed_files=["src/app.py"])
            next_action = load_next_action(analyze_payload)
            report_path = repo_root / ".ai" / "codegraph" / "loop-breaker-report.json"

            self.assertTrue(report_path.exists())
            self.assertEqual(next_action["recommended_test_scope"], "full")
            self.assertEqual(next_action["verification_budget"], "B4")

    def test_loop_escalation_updates_next_action(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "next-action-loop"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            analyze_change(repo_cig, repo_root, changed_files=["src/app.py"])
            break_login_behavior(repo_root)

            for _ in range(4):
                result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                self.assertNotEqual(result.returncode, 0)

            analyze_payload = analyze_change(repo_cig, repo_root, changed_files=["src/app.py"])
            next_action = load_next_action(analyze_payload)

            self.assertIn("repair_loop", next_action)
            self.assertTrue(next_action["repair_loop"]["active"])
            self.assertEqual(next_action["repair_loop"]["repeat_count"], 4)
            self.assertIn("expanded_chain_summary", next_action)
            self.assertIn("contracts", next_action["expanded_chain_summary"])

    def test_bypass_changes_do_not_enter_repair_loop(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "bypass-no-loop"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            ensure_plain_docs(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_change(repo_cig, repo_root, changed_files=["docs/archive/note.md"])
            result = run_finish_raw(repo_cig, repo_root, changed_files=["docs/archive/note.md"])

            self.assertEqual(result.returncode, 0)
            self.assertFalse((repo_root / ".ai" / "codegraph" / "repair-attempts.jsonl").exists())

    def test_diagnose_loop_returns_changed_file_context(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "diagnose-loop"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            analyze_change(repo_cig, repo_root, changed_files=["src/app.py"])
            break_login_behavior(repo_root)

            for _ in range(3):
                result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                self.assertNotEqual(result.returncode, 0)

            payload = diagnose_loop(repo_cig, repo_root, changed_files=["src/app.py"])

            self.assertEqual(payload["repeat_count"], 3)
            self.assertEqual(payload["recommended_escalation"], "L2")


if __name__ == "__main__":
    unittest.main()
