import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / ".agents" / "skills" / "zhanggong-impact-blueprint" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate_report
import handoff
import profiles
import test_command_resolver
import test_stage18_workflow as stage18
import trust_policy


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CIG_SCRIPT = REPO_ROOT / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"


def run_cig_env(
    repo_root: pathlib.Path,
    *args: str,
    env: dict[str, str] | None = None,
    expect_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(CIG_SCRIPT), *args],
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
        env=env,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def run_cig_json_env(repo_root: pathlib.Path, *args: str, env: dict[str, str] | None = None) -> dict:
    result = run_cig_env(repo_root, *args, env=env)
    return json.loads(result.stdout)


def write_python_repo_in_test_dir(repo_root: pathlib.Path, *, failing_message: str = "baseline") -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "test").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "src" / "app.py").write_text(
        "def login(user_name, password):\n"
        "    if not user_name or not password:\n"
        "        return {'ok': False, 'message': 'missing'}\n"
        f"    return {{'ok': True, 'message': '{failing_message}'}}\n",
        encoding="utf-8",
    )
    (repo_root / "test" / "test_app.py").write_text(
        "import unittest\n"
        "from src.app import login\n\n"
        "class LoginTest(unittest.TestCase):\n"
        "    def test_login(self):\n"
        "        self.assertEqual(login('demo', 'secret')['message'], 'baseline')\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )


def read_test_results(repo_root: pathlib.Path) -> dict:
    return stage18.read_json(repo_root / ".ai" / "codegraph" / "test-results.json")


class Stage18_1WorkflowTest(unittest.TestCase):
    def test_preflight_treats_nt_as_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            script = repo_root / "test-blueprint.sh"
            script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            payload = test_command_resolver.preflight_test_command(["test-blueprint.sh"], repo_root, "nt")
            issue_kinds = {item["kind"] for item in payload["issues"]}
            self.assertEqual(payload["status"], "fail")
            self.assertIn("shell_script_on_windows", issue_kinds)

    def test_preflight_sh_command_on_nt_fails_not_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            script = repo_root / "test-blueprint.sh"
            script.write_text("#!/usr/bin/env bash\r\necho ok\r\n", encoding="utf-8")
            payload = test_command_resolver.preflight_test_command(["test-blueprint.sh"], repo_root, "nt")
            issue_kinds = {item["kind"] for item in payload["issues"]}
            self.assertEqual(payload["status"], "fail")
            self.assertIn("shell_script_on_windows", issue_kinds)
            self.assertIn("crlf_shell_script", issue_kinds)

    def test_after_edit_passes_platform_in_a_form_preflight_understands(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_python_repo(repo_root)
            stage18.setup_repo(repo_root, profile="python-basic")
            config = stage18.read_json(stage18.config_path(repo_root))
            config["python"]["test_command"] = ["test-blueprint.sh"]
            stage18.write_json(stage18.config_path(repo_root), config)
            (repo_root / "test-blueprint.sh").write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
            stage18.analyze_json(repo_root, seed="fn:src/app.py:login", changed_files=["src/app.py"])
            result = stage18.run_cig(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
                expect_success=False,
            )
            self.assertIn("TEST_COMMAND_PREFLIGHT_FAILED", result.stderr)

    def test_cli_json_output_survives_gbk_encoding_with_unicode_checkmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            (repo_root / "src").mkdir(parents=True, exist_ok=True)
            (repo_root / "tests").mkdir(parents=True, exist_ok=True)
            (repo_root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "stage18-gbk",
                        "private": True,
                        "type": "module",
                        "scripts": {"test": "node --test"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "cli.js").write_text(
                "export function runCommand(name) {\n"
                "  return `baseline:${name}`;\n"
                "}\n",
                encoding="utf-8",
            )
            (repo_root / "tests" / "cli.test.js").write_text(
                "import test from 'node:test';\n"
                "import assert from 'node:assert/strict';\n"
                "import { runCommand } from '../src/cli.js';\n\n"
                "test('prints a unicode checkmark', () => {\n"
                "  console.log('✔ stable unicode marker');\n"
                "  assert.equal(runCommand('demo'), 'baseline:demo');\n"
                "});\n",
                encoding="utf-8",
            )
            stage18.setup_repo(repo_root, profile="node-cli")
            stage18.analyze_json(repo_root, seed="fn:src/cli.js:runCommand", changed_files=["src/cli.js"])
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "gbk"
            env.pop("PYTHONUTF8", None)
            result = run_cig_env(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/cli.js",
                "--test-scope",
                "configured",
                env=env,
                expect_success=True,
            )
            tests = read_test_results(repo_root)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("UnicodeEncodeError", result.stderr)
            self.assertTrue(tests["tests_passed"])
            self.assertIn("\\u2714", result.stdout)

    def test_python_repo_with_singular_test_dir_uses_test_not_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo_in_test_dir(repo_root)
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={},
                adapter_name="python",
                profile_name="python-basic",
            )
            self.assertEqual(payload["selected_test_command"], "python -m unittest discover -s test -p test_*.py")

    def test_python_repo_with_tests_dir_keeps_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_python_repo(repo_root)
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={},
                adapter_name="python",
                profile_name="python-basic",
            )
            self.assertEqual(payload["selected_test_command"], "python -m unittest discover -s tests -p test_*.py")

    def test_python_calibrate_test_dirs_match_selected_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo_in_test_dir(repo_root)
            stage18.setup_repo(repo_root, profile="python-basic")
            payload = stage18.run_cig_json(
                repo_root,
                "calibrate",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
            )
            self.assertEqual(payload["test_dirs"], ["test"])
            self.assertIn("-s test", payload["test_command"]["selected_test_command"])

    def test_failure_signature_ignores_unittest_duration(self):
        output_a = (
            "F\n"
            "FAIL: test_login (test_app.LoginTest.test_login)\n"
            "AssertionError: 'broken-a' != 'baseline'\n"
            "Ran 1 test in 0.010s\n"
            "FAILED (failures=1)\n"
        )
        output_b = output_a.replace("0.010s", "0.011s")
        sig_a = test_command_resolver.compute_failure_signature(
            command=["python", "-m", "unittest"],
            exit_code=1,
            output_text=output_a,
            failed_tests=["test_app.LoginTest.test_login"],
        )
        sig_b = test_command_resolver.compute_failure_signature(
            command=["python", "-m", "unittest"],
            exit_code=1,
            output_text=output_b,
            failed_tests=["test_app.LoginTest.test_login"],
        )
        self.assertEqual(sig_a, sig_b)

    def test_failure_signature_ignores_absolute_temp_paths(self):
        output_a = (
            "Traceback (most recent call last):\n"
            "File \"C:\\Users\\alice\\AppData\\Local\\Temp\\tmpabc123\\tests\\test_app.py\", line 12, in test_login\n"
            "AssertionError: bad\n"
        )
        output_b = output_a.replace(
            "C:\\Users\\alice\\AppData\\Local\\Temp\\tmpabc123",
            "/tmp/tmpxyz789",
        ).replace("line 12", "line 98")
        sig_a = test_command_resolver.compute_failure_signature(
            command=["python", "-m", "unittest"],
            exit_code=1,
            output_text=output_a,
            failed_tests=[],
        )
        sig_b = test_command_resolver.compute_failure_signature(
            command=["python", "-m", "unittest"],
            exit_code=1,
            output_text=output_b,
            failed_tests=[],
        )
        self.assertEqual(sig_a, sig_b)

    def test_same_baseline_failure_is_no_regression_across_repeated_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_python_repo(repo_root, failing_message="broken-a")
            stage18.setup_repo(repo_root, profile="python-basic")
            stage18.analyze_json(repo_root, seed="fn:src/app.py:login", changed_files=["src/app.py"])
            stage18.run_cig(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
                expect_success=False,
            )
            stage18.run_cig_json(
                repo_root,
                "baseline",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--capture-current",
            )
            second = stage18.run_cig_json(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
            )
            self.assertEqual(second["tests"]["regression_status"], "no_regression")

    def test_baseline_regression_status_is_stable_for_10_repeats(self):
        failures: list[dict] = []
        for index in range(10):
            with tempfile.TemporaryDirectory(prefix=f"stage18_1_repeat_{index}_") as tmp:
                repo_root = pathlib.Path(tmp)
                stage18.write_python_repo(repo_root, failing_message="broken-a")
                stage18.setup_repo(repo_root, profile="python-basic")
                stage18.analyze_json(repo_root, seed="fn:src/app.py:login", changed_files=["src/app.py"])
                stage18.run_cig(
                    repo_root,
                    "finish",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(stage18.config_path(repo_root)),
                    "--changed-file",
                    "src/app.py",
                    "--test-scope",
                    "configured",
                    expect_success=False,
                )
                stage18.run_cig_json(
                    repo_root,
                    "baseline",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(stage18.config_path(repo_root)),
                    "--capture-current",
                )
                second = stage18.run_cig(
                    repo_root,
                    "finish",
                    "--workspace-root",
                    str(repo_root),
                    "--config",
                    str(stage18.config_path(repo_root)),
                    "--changed-file",
                    "src/app.py",
                    "--test-scope",
                    "configured",
                    expect_success=False,
                )
                results = read_test_results(repo_root)
                if second.returncode != 0 or results.get("regression_status") != "no_regression":
                    failures.append(
                        {
                            "index": index,
                            "returncode": second.returncode,
                            "regression_status": results.get("regression_status"),
                            "baseline_failure_signature": results.get("baseline_failure_signature"),
                            "current_failure_signature": results.get("current_failure_signature"),
                        }
                    )
        self.assertFalse(failures, json.dumps(failures, ensure_ascii=False, indent=2))

    def test_handoff_clears_previous_error_after_successful_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_python_repo(repo_root, failing_message="broken")
            stage18.setup_repo(repo_root, profile="python-basic")
            stage18.analyze_json(repo_root, seed="fn:src/app.py:login", changed_files=["src/app.py"])
            stage18.run_cig(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
                expect_success=False,
            )
            stage18.write_python_repo(repo_root, failing_message="baseline")
            stage18.run_cig_json(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
            )
            handoff_text = (repo_root / ".ai" / "codegraph" / "handoff" / "latest.md").read_text(encoding="utf-8")
            self.assertNotIn("## Last error", handoff_text)

    def test_handoff_recent_successful_step_is_finish_after_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_python_repo(repo_root)
            stage18.setup_repo(repo_root, profile="python-basic")
            stage18.analyze_json(repo_root, seed="fn:src/app.py:login", changed_files=["src/app.py"])
            stage18.run_cig_json(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
            )
            handoff_text = (repo_root / ".ai" / "codegraph" / "handoff" / "latest.md").read_text(encoding="utf-8")
            self.assertIn("Recent successful step: finish", handoff_text)

    def test_handoff_tests_passed_matches_test_results_after_fail_then_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_python_repo(repo_root, failing_message="broken")
            stage18.setup_repo(repo_root, profile="python-basic")
            stage18.analyze_json(repo_root, seed="fn:src/app.py:login", changed_files=["src/app.py"])
            stage18.run_cig(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
                expect_success=False,
            )
            stage18.write_python_repo(repo_root, failing_message="baseline")
            stage18.run_cig_json(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
            )
            results = read_test_results(repo_root)
            handoff_text = (repo_root / ".ai" / "codegraph" / "handoff" / "latest.md").read_text(encoding="utf-8")
            self.assertIn(f"Tests passed: {results['tests_passed']}", handoff_text)

    def test_seed_selection_required_next_action_does_not_recommend_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_multi_function_python_file(repo_root, count=12)
            stage18.setup_repo(repo_root, profile="python-basic")
            result = stage18.run_cig(
                repo_root,
                "analyze",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/multi.py",
                expect_success=False,
            )
            self.assertNotEqual(result.returncode, 0)
            next_action = stage18.read_json(repo_root / ".ai" / "codegraph" / "next-action.json")
            self.assertEqual(next_action["can_edit_now"], False)
            self.assertEqual(next_action["recommended_test_scope"], "none")
            self.assertFalse(any(" finish " in f" {item} " for item in next_action["recommended_commands"]))

    def test_seed_selection_required_next_action_recommends_seed_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_multi_function_python_file(repo_root, count=12)
            stage18.setup_repo(repo_root, profile="python-basic")
            stage18.run_cig(
                repo_root,
                "analyze",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/multi.py",
                expect_success=False,
            )
            next_action = stage18.read_json(repo_root / ".ai" / "codegraph" / "next-action.json")
            self.assertEqual(next_action["status"], "seed_selection_required")
            self.assertEqual(next_action["suggested_next_step"], "Choose one seed and rerun analyze.")
            self.assertTrue(all("--seed" in item for item in next_action["recommended_commands"]))

    def test_seed_selection_required_outputs_consistent_candidate_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_multi_function_python_file(repo_root, count=12)
            stage18.setup_repo(repo_root, profile="python-basic")
            stage18.run_cig(
                repo_root,
                "analyze",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(stage18.config_path(repo_root)),
                "--changed-file",
                "src/multi.py",
                expect_success=False,
            )
            next_action = stage18.read_json(repo_root / ".ai" / "codegraph" / "next-action.json")
            last_error = stage18.read_json(repo_root / ".ai" / "codegraph" / "logs" / "last-error.json")
            seed_candidates = stage18.read_json(repo_root / ".ai" / "codegraph" / "seed-candidates.json")
            self.assertEqual(len(next_action["candidate_seeds"]), len(last_error["alternatives"]))
            self.assertEqual(len(next_action["candidate_seeds"]), len(seed_candidates["candidates"]))

    def test_low_workspace_noise_is_not_used_as_low_trust_reason(self):
        axes = trust_policy.trust_axes_payload(
            graph_freshness="fresh",
            generated_noise=False,
            dependency_fingerprint_status="unknown",
            context_confidence="missing",
            adapter_confidence="high",
            test_signal="unknown",
        )
        explanation = " ".join(axes["trust_explanation"])
        self.assertNotIn("workspace_noise is low", explanation)

    def test_trust_explanation_names_actual_lowering_axis(self):
        payload = generate_report.multidimensional_trust_payload(
            build_decision={
                "graph_trust": "high",
                "graph_freshness": "fresh",
                "generated_noise": [],
                "trust_axes": {
                    "graph_freshness": "fresh",
                    "workspace_noise": "low",
                    "dependency_confidence": "low",
                    "context_confidence": "missing",
                    "adapter_confidence": "high",
                    "test_signal": "unknown",
                    "overall_trust": "low",
                },
            },
            parser_trust="high",
            dependency_state="unknown",
            coverage={"status": "unknown"},
            context={"seed_source": "fallback"},
            test_signal={"status": "not-run", "full_suite": False},
        )
        explanation = " ".join(payload["trust_explanation"])
        self.assertTrue(
            "Dependency confidence" in explanation
            or "context_confidence" in explanation
            or "test_signal" in explanation
        )

    def test_fresh_graph_low_overall_trust_explains_non_freshness_reason(self):
        payload = generate_report.multidimensional_trust_payload(
            build_decision={
                "graph_trust": "medium",
                "graph_freshness": "fresh",
                "generated_noise": [],
                "trust_axes": {
                    "graph_freshness": "fresh",
                    "workspace_noise": "low",
                    "dependency_confidence": "high",
                    "context_confidence": "missing",
                    "adapter_confidence": "low",
                    "test_signal": "none",
                    "overall_trust": "low",
                },
            },
            parser_trust="medium",
            dependency_state="not_applicable",
            coverage={"status": "unknown"},
            context={"seed_source": "fallback"},
            test_signal={"status": "not-run", "full_suite": False},
        )
        explanation = " ".join(payload["trust_explanation"])
        self.assertIn("Graph is fresh", explanation)
        self.assertNotIn("because workspace_noise is low", explanation)

    def test_repo_config_list_test_command_is_explicit(self):
        self.assertTrue(test_command_resolver.is_explicit_command(["node", "--test"]))

    def test_repo_config_list_test_command_beats_package_json_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_ts_repo(repo_root, scripts={"test:run": "vitest run", "test": "node --test"})
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={"tsjs": {"test_command": ["node", "--test"]}},
                adapter_name="tsjs",
                profile_name="node-cli",
            )
            self.assertEqual(payload["selected_test_command"], "node --test")
            self.assertEqual(payload["test_command_source"], "repo_config:tsjs.test_command")

    def test_empty_list_test_command_is_treated_as_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            stage18.write_ts_repo(repo_root, scripts={"test:run": "vitest run"})
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={"tsjs": {"test_command": []}},
                adapter_name="tsjs",
                profile_name="node-cli",
            )
            self.assertEqual(payload["selected_test_command"], "npm run test:run")


if __name__ == "__main__":
    unittest.main()
