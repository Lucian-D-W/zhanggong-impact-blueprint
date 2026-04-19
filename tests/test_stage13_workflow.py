import json
import importlib.util
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / ".agents" / "skills" / "code-impact-guardian" / "scripts"))

import parser_backends

from tests.test_stage11_workflow import (
    build_repo,
    config_path,
    setup_repo,
    write_python_repo_with_dependencies,
    write_python_repo_with_two_tests,
)
from tests.test_stage7_workflow import copy_single_skill_folder, run_json, write_python_repo


def analyze_repo(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *,
    seed: str | None = None,
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
    if seed:
        command.extend(["--seed", seed])
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
    test_scope: str | None = None,
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
    if test_scope:
        command.extend(["--test-scope", test_scope])
    if allow_fallback:
        command.append("--allow-fallback")
    return run_json(command, cwd=repo_root)


def recommend_tests(repo_cig: pathlib.Path, repo_root: pathlib.Path, task_id: str) -> dict:
    return run_json(
        [
            sys.executable,
            str(repo_cig),
            "recommend-tests",
            "--workspace-root",
            str(repo_root),
            "--config",
            str(config_path(repo_root)),
            "--task-id",
            task_id,
        ],
        cwd=repo_root,
    )


class Stage13WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = pathlib.Path(__file__).resolve().parents[1]
        cls.cig_script = cls.repo_root / ".agents" / "skills" / "code-impact-guardian" / "cig.py"
        spec = importlib.util.spec_from_file_location("stage13_cig_module", cls.cig_script)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load Code Impact Guardian module for Stage 13 tests")
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

    def test_iter_matching_files_prunes_excluded_dirs(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project_root = pathlib.Path(tmp)
            (project_root / "src").mkdir(parents=True, exist_ok=True)
            (project_root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (project_root / "dist" / "nested").mkdir(parents=True, exist_ok=True)
            (project_root / "dist" / "nested" / "bundle.py").write_text("print('skip')\n", encoding="utf-8")

            visited_dist = {"value": False}
            original_walk = parser_backends.os.walk

            def guarded_walk(top, topdown=True, onerror=None, followlinks=False):
                for current_root, dirs, files in original_walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks):
                    if pathlib.Path(current_root).name == "dist":
                        visited_dist["value"] = True
                    yield current_root, dirs, files

            with mock.patch("parser_backends.os.walk", side_effect=guarded_walk):
                results = parser_backends.iter_matching_files(
                    project_root,
                    ["src/**/*.py", "src/*.py", "dist/**/*.py"],
                    exclude_dirs=["dist"],
                )

            self.assertEqual(
                [path.relative_to(project_root).as_posix() for path in results],
                ["src/main.py"],
            )
            self.assertFalse(visited_dist["value"])

    def test_configured_exclude_dirs_allows_explicit_empty_list(self):
        self.assertEqual(parser_backends.configured_exclude_dirs({"graph": {"exclude_dirs": []}}), [])

    def test_iter_matching_files_allows_explicit_include_inside_excluded_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project_root = pathlib.Path(tmp)
            (project_root / "dist" / "sub").mkdir(parents=True, exist_ok=True)
            (project_root / "dist" / "sub" / "keep.py").write_text("print('keep')\n", encoding="utf-8")
            (project_root / "dist" / "sub" / "skip.py").write_text("print('skip')\n", encoding="utf-8")

            results = parser_backends.iter_matching_files(
                project_root,
                ["dist/**/*.py"],
                include_files=["dist/sub/keep.py"],
                exclude_dirs=["dist"],
            )

            self.assertEqual(
                [path.relative_to(project_root).as_posix() for path in results],
                ["dist/sub/keep.py"],
            )

    def test_iter_matching_files_normalizes_dot_prefixed_paths(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project_root = pathlib.Path(tmp)
            (project_root / "src").mkdir(parents=True, exist_ok=True)
            (project_root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (project_root / "dist").mkdir(parents=True, exist_ok=True)
            (project_root / "dist" / "bundle.py").write_text("print('bundle')\n", encoding="utf-8")

            results = parser_backends.iter_matching_files(
                project_root,
                ["./src/*.py", "./src/**/*.py", "./dist/*.py", "./dist/**/*.py"],
                include_files=["./src/main.py", ".\\dist\\bundle.py"],
                exclude_dirs=[],
            )

            self.assertEqual(
                [path.relative_to(project_root).as_posix() for path in results],
                ["dist/bundle.py", "src/main.py"],
            )

    def test_recommend_tests_maps_python_unittest_seed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "recommend-python"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            payload = recommend_tests(repo_cig, repo_root, analyze_payload["task_id"])

            self.assertEqual(payload["mapping_status"], "mapped")
            commands = {tuple(item["command"]) for item in payload["recommended_tests"]}
            self.assertIn(
                ("python", "-m", "unittest", "tests.test_app.LoginTest.test_login_accepts_valid_credentials"),
                commands,
            )
            self.assertIn(
                ("python", "-m", "unittest", "tests.test_app.LoginTest.test_login_rejects_missing_password"),
                commands,
            )
            self.assertTrue(all(item["confidence"] == "high" for item in payload["recommended_tests"]))
            self.assertTrue(all(item["reason"] == "direct COVERS edge" for item in payload["recommended_tests"]))

    def test_recommend_tests_falls_back_when_mapping_unknown(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "recommend-fallback"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_repo(
                repo_cig,
                repo_root,
                seed="file:src/app.py",
                changed_files=["src/app.py"],
                allow_fallback=True,
            )
            payload = recommend_tests(repo_cig, repo_root, analyze_payload["task_id"])

            self.assertEqual(payload["mapping_status"], "unavailable")
            self.assertEqual(payload["recommended_tests"], [])
            self.assertEqual(payload["fallback_command"][:4], ["python", "-m", "unittest", "discover"])

    def test_finish_targeted_runs_only_direct_python_unittest(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "finish-targeted"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            app_path = repo_root / "src" / "app.py"
            app_path.write_text(
                app_path.read_text(encoding="utf-8").replace("'baseline'", "'targeted'"),
                encoding="utf-8",
            )

            finish_payload = finish_repo(
                repo_cig,
                repo_root,
                changed_files=["src/app.py"],
                test_scope="targeted",
            )

            command_text = " ".join(" ".join(command) for command in finish_payload["tests"]["commands"])
            self.assertEqual(finish_payload["tests"]["requested_test_scope"], "targeted")
            self.assertEqual(finish_payload["tests"]["effective_test_scope"], "targeted")
            self.assertFalse(finish_payload["tests"]["full_suite"])
            self.assertNotIn("discover", command_text)
            self.assertIn("tests.test_app.LoginTest.test_login_accepts_valid_credentials", command_text)
            self.assertIn("tests.test_app.LoginTest.test_login_rejects_missing_password", command_text)
            self.assertEqual(finish_payload["tests"]["tests_run"], 2)
            self.assertEqual(
                finish_payload["tests"]["command"],
                finish_payload["tests"]["commands"][0],
            )

    def test_finish_targeted_persists_all_mapped_commands(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "finish-targeted-command-persistence"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            app_path = repo_root / "src" / "app.py"
            app_path.write_text(
                app_path.read_text(encoding="utf-8").replace("'baseline'", "'targeted'"),
                encoding="utf-8",
            )

            finish_repo(
                repo_cig,
                repo_root,
                changed_files=["src/app.py"],
                test_scope="targeted",
            )

            db_path = repo_root / ".ai" / "codegraph" / "codegraph.db"
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT command_json, attrs_json FROM test_runs ORDER BY rowid DESC LIMIT 1"
                ).fetchone()

            self.assertIsNotNone(row)
            command_json, attrs_json = row
            persisted_command = json.loads(command_json)
            persisted_attrs = json.loads(attrs_json)
            self.assertTrue(persisted_command)
            self.assertTrue(persisted_attrs["commands"])
            persisted_text = " ".join(" ".join(command) for command in persisted_attrs["commands"])
            self.assertIn("tests.test_app.LoginTest.test_login_accepts_valid_credentials", persisted_text)
            self.assertIn("tests.test_app.LoginTest.test_login_rejects_missing_password", persisted_text)

    def test_finish_targeted_falls_back_to_configured_when_no_mapping(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "finish-configured-fallback"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_repo(
                repo_cig,
                repo_root,
                seed="file:src/app.py",
                changed_files=["src/app.py"],
                allow_fallback=True,
            )
            app_path = repo_root / "src" / "app.py"
            app_path.write_text(
                app_path.read_text(encoding="utf-8").replace("'baseline'", "'configured'"),
                encoding="utf-8",
            )

            finish_payload = finish_repo(
                repo_cig,
                repo_root,
                changed_files=["src/app.py"],
                test_scope="targeted",
                allow_fallback=True,
            )

            command_text = " ".join(finish_payload["tests"]["command"])
            self.assertEqual(finish_payload["tests"]["requested_test_scope"], "targeted")
            self.assertEqual(finish_payload["tests"]["effective_test_scope"], "configured")
            self.assertTrue(finish_payload["tests"]["full_suite"])
            self.assertIn("discover", command_text)
            self.assertIn("mapping", finish_payload["tests"]["test_scope_reason"].lower())

    def test_coveragepy_missing_runs_plain_tests_and_marks_coverage_unavailable(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "coveragepy-missing"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_repo(
                repo_cig,
                repo_root,
                seed="fn:src/app.py:login",
                changed_files=["src/app.py"],
            )
            app_path = repo_root / "src" / "app.py"
            app_path.write_text(
                app_path.read_text(encoding="utf-8").replace("'baseline'", "'plain-fallback'"),
                encoding="utf-8",
            )

            with mock.patch.object(
                self.cig_module.after_edit_update,
                "coveragepy_available",
                return_value=False,
                create=True,
            ):
                finish_payload = self.cig_module.finalize_after_edit(
                    workspace_root=repo_root,
                    config_path=config_path(repo_root),
                    task_id=analyze_payload["task_id"],
                    seed=analyze_payload["seed"],
                    changed_files=["src/app.py"],
                    command_name="finish",
                    report_mode="brief",
                    test_scope="configured",
                )

            tests_payload = finish_payload["tests"]
            self.assertEqual(tests_payload["status"], "passed")
            self.assertTrue(tests_payload["tests_passed"])
            self.assertFalse(tests_payload["coverage_available"])
            self.assertEqual(tests_payload["coverage_status"], "unavailable")
            self.assertIn("coverage.py is not installed", tests_payload["coverage_reason"])
            self.assertIsNone(tests_payload["coverage_path"])
            self.assertEqual(tests_payload["tests_run"], 1)
            self.assertIn("-m unittest discover", " ".join(tests_payload["command"]))
            self.assertNotIn("coverage run", " ".join(tests_payload["command"]))

    def test_next_action_prefers_targeted_for_low_risk_direct_tests(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "next-action-targeted"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            analyze_payload = analyze_repo(repo_cig, repo_root, changed_files=["src/app.py"])
            next_action = json.loads(pathlib.Path(analyze_payload["machine_outputs"]["next_action_path"]).read_text(encoding="utf-8"))

            self.assertEqual(next_action["recommended_test_scope"], "targeted")
            self.assertTrue(next_action["can_edit_now"])
            self.assertIn("src/app.py", next_action["must_read_first"])
            self.assertTrue(any("--test-scope targeted" in item for item in next_action["recommended_commands"]))
            self.assertEqual(next_action["trust"]["dependency"], "unchanged")

    def test_next_action_raises_scope_for_dependency_changed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "next-action-dependency"
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

            self.assertIn(next_action["recommended_test_scope"], {"configured", "full"})
            self.assertNotEqual(next_action["recommended_test_scope"], "targeted")
            self.assertIn(next_action["risk_level"], {"medium", "high"})
            self.assertEqual(next_action["trust"]["dependency"], "changed")

    def test_multidimensional_trust_never_high_when_dependency_unknown(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "trust-unknown"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_dependencies(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")

            build_repo(repo_cig, repo_root)
            manifest_path = repo_root / ".ai" / "codegraph" / "build-manifest.json"
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload.setdefault("meta", {}).pop("dependency_fingerprint", None)
            manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            payload = build_repo(repo_cig, repo_root)
            trust = payload["build_decision"]["trust"]

            self.assertEqual(trust["dependency"], "unknown")
            self.assertNotEqual(trust["overall"], "high")
            self.assertEqual(trust["graph"], payload["build_decision"]["graph_trust"])

    def test_next_action_raises_risk_when_tests_fail(self):
        payload = self.cig_module.next_action_payload(
            workspace_root=self.repo_root,
            config_path=config_path(self.repo_root),
            command_name="finish",
            task_id=None,
            seed="fn:src/app.py:login",
            report_payload={
                "brief": {
                    "test_signal": {"affected_tests_found": True},
                    "report_completeness": {"level": "high"},
                    "trust": {
                        "graph": "high",
                        "parser": "high",
                        "dependency": "unchanged",
                        "test_signal": "failed",
                        "coverage": "direct-covered",
                        "context": "explicit",
                        "overall": "medium",
                    },
                    "direct_impact_summary": {},
                },
                "direct": {"tests": ["test:tests/test_app.py:LoginTest.test_login"]},
            },
            build_payload={"build_decision": {"graph_trust": "high", "dependency_fingerprint_status": "unchanged"}},
            seed_selection={"reason": "explicit seed", "confidence": 1.0},
            tests_payload={"status": "failed", "tests_passed": False},
            fallback_used=False,
        )

        self.assertEqual(payload["recommended_action"], "inspect_failed_tests")
        self.assertIn(payload["risk_level"], {"medium", "high"})
        self.assertNotEqual(payload["risk_level"], "low")
        self.assertIn("failing test output", payload["suggested_next_step"])

    def test_next_action_skipped_tests_do_not_claim_pass(self):
        payload = self.cig_module.next_action_payload(
            workspace_root=self.repo_root,
            config_path=config_path(self.repo_root),
            command_name="finish",
            task_id=None,
            seed="file:src/app.py",
            report_payload={
                "brief": {
                    "test_signal": {"affected_tests_found": False},
                    "report_completeness": {"level": "high"},
                    "trust": {
                        "graph": "high",
                        "parser": "high",
                        "dependency": "unchanged",
                        "test_signal": "not-run",
                        "coverage": "unknown",
                        "context": "explicit",
                        "overall": "medium",
                    },
                    "direct_impact_summary": {},
                },
                "direct": {"tests": []},
            },
            build_payload={"build_decision": {"graph_trust": "high", "dependency_fingerprint_status": "unchanged"}},
            seed_selection={"reason": "explicit seed", "confidence": 1.0},
            tests_payload={"status": "skipped", "tests_passed": False},
            fallback_used=False,
        )

        self.assertNotIn("Tests passed", payload["suggested_next_step"])
        self.assertIn("warning", payload["suggested_next_step"].lower())

    def test_skill_doc_mentions_health_next_action_and_test_scope(self):
        skill_path = pathlib.Path(__file__).resolve().parents[1] / ".agents" / "skills" / "code-impact-guardian" / "SKILL.md"
        skill_text = skill_path.read_text(encoding="utf-8")

        self.assertIn("health", skill_text)
        self.assertIn("next-action.json", skill_text)
        self.assertIn("--test-scope targeted", skill_text)


if __name__ == "__main__":
    unittest.main()
