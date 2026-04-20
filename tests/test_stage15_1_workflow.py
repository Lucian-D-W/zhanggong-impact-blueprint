import json
import pathlib
import sys
import tempfile
import unittest

from tests.test_stage11_workflow import config_path, setup_repo, write_python_repo_with_two_tests
from tests.test_stage7_workflow import copy_single_skill_folder, run_json


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


def assess_mutation(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *,
    target_path: str,
    action: str,
) -> dict:
    return run_json(
        [
            sys.executable,
            str(repo_cig),
            "assess-mutation",
            "--workspace-root",
            str(repo_root),
            "--path",
            target_path,
            "--action",
            action,
        ],
        cwd=repo_root,
    )


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_working_note(repo_root: pathlib.Path, relative_path: str = "mainstone.md") -> None:
    (repo_root / relative_path).write_text(
        "# Working Notes\n\n"
        "Current status:\n"
        "- Stage 15.1 design in progress\n\n"
        "Next steps:\n"
        "- tighten verification budget behavior for docs\n"
        "- keep a record of finish --test-scope choices\n",
        encoding="utf-8",
    )


class Stage151WorkflowTest(unittest.TestCase):
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

    def test_declared_working_note_is_lightweight_even_with_guard_patterns(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "working-note-lightweight"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            write_working_note(repo_root)

            config = read_json(config_path(repo_root))
            config["doc_roles"] = {
                "working_note_globs": ["mainstone.md"],
                "protected_doc_globs": ["mainstone.md"],
            }
            write_json(config_path(repo_root), config)

            payload = classify_change(repo_cig, repo_root, changed_files=["mainstone.md"])

            self.assertEqual(payload["change_class"], "lightweight")
            self.assertEqual(payload["verification_budget"], "B1")
            self.assertEqual(payload["recommended_test_scope"], "none")
            self.assertEqual(payload["files"][0]["doc_role"], "working_note")
            self.assertEqual(payload["files"][0]["role_source"], "declared")

    def test_rule_doc_stays_guarded_even_if_declared_working_note(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "rule-doc-wins"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            config = read_json(config_path(repo_root))
            config["doc_roles"] = {
                "working_note_globs": ["docs/rules/auth.md"],
                "protected_doc_globs": ["docs/rules/auth.md"],
            }
            write_json(config_path(repo_root), config)

            payload = classify_change(repo_cig, repo_root, changed_files=["docs/rules/auth.md"])

            self.assertEqual(payload["change_class"], "guarded")
            self.assertIn(payload["verification_budget"], {"B2", "B3", "B4"})
            self.assertEqual(payload["files"][0]["doc_role"], "rule_doc")

    def test_assess_mutation_move_requires_confirmation_for_protected_working_note(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "mutation-move"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            write_working_note(repo_root)

            config = read_json(config_path(repo_root))
            config["doc_roles"] = {
                "working_note_globs": ["mainstone.md"],
                "protected_doc_globs": ["mainstone.md"],
            }
            write_json(config_path(repo_root), config)

            payload = assess_mutation(repo_cig, repo_root, target_path="mainstone.md", action="move")

            self.assertEqual(payload["doc_role"], "working_note")
            self.assertTrue(payload["requires_user_confirmation"])
            self.assertEqual(payload["guard_level"], "confirm_before_move")

    def test_assess_mutation_delete_is_recycle_only(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "mutation-delete"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            write_working_note(repo_root, "chaos-notes.md")

            payload = assess_mutation(repo_cig, repo_root, target_path="chaos-notes.md", action="delete")

            self.assertEqual(payload["delete_mode"], "recycle_only")
            self.assertFalse(payload["permanent_delete_allowed"])

    def test_assess_mutation_permanent_delete_requires_strict_approval(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "mutation-permadelete"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            write_working_note(repo_root)

            payload = assess_mutation(repo_cig, repo_root, target_path="mainstone.md", action="permanent_delete")

            self.assertTrue(payload["requires_strict_user_approval"])
            self.assertFalse(payload["allowed_without_approval"])
            self.assertEqual(payload["guard_level"], "never_delete_without_approval")

    def test_working_note_heuristic_handles_varied_name(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "heuristic-working-note"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            write_working_note(repo_root, "chaos-log-0420.md")

            payload = classify_change(repo_cig, repo_root, changed_files=["chaos-log-0420.md"])

            self.assertEqual(payload["change_class"], "lightweight")
            self.assertEqual(payload["files"][0]["doc_role"], "working_note")
            self.assertEqual(payload["files"][0]["role_source"], "heuristic")


if __name__ == "__main__":
    unittest.main()

