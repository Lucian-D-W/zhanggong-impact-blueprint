import json
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / ".agents" / "skills" / "zhanggong-impact-blueprint" / "scripts"))

import adapters
import recommend_tests
import test_command_resolver
import trust_policy


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CIG_SCRIPT = REPO_ROOT / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"


def config_path(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / ".zhanggong-impact-blueprint" / "config.json"


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_cig(repo_root: pathlib.Path, *args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(CIG_SCRIPT), *args],
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def run_cig_json(repo_root: pathlib.Path, *args: str) -> dict:
    result = run_cig(repo_root, *args)
    return json.loads(result.stdout)


def init_git_repo(repo_root: pathlib.Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, text=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo_root, check=True, text=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Codex"], cwd=repo_root, check=True, text=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True, text=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo_root, check=True, text=True, capture_output=True)


def setup_repo(repo_root: pathlib.Path, *, profile: str | None = None, extra_args: list[str] | None = None) -> dict:
    command = [
        "setup",
        "--workspace-root",
        str(repo_root),
        "--project-root",
        ".",
    ]
    if profile:
        command.extend(["--profile", profile])
    command.extend(extra_args or [])
    return run_cig_json(repo_root, *command)


def analyze_json(repo_root: pathlib.Path, *, seed: str | None = None, changed_files: list[str] | None = None, extra_args: list[str] | None = None) -> dict:
    command = [
        "analyze",
        "--workspace-root",
        str(repo_root),
        "--config",
        str(config_path(repo_root)),
        "--json",
    ]
    if seed:
        command.extend(["--seed", seed])
    for changed_file in changed_files or []:
        command.extend(["--changed-file", changed_file])
    command.extend(extra_args or [])
    return run_cig_json(repo_root, *command)


def write_python_repo(repo_root: pathlib.Path, *, failing_message: str = "baseline") -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "src" / "app.py").write_text(
        "def login(user_name, password):\n"
        "    if not user_name or not password:\n"
        "        return {'ok': False, 'message': 'missing'}\n"
        f"    return {{'ok': True, 'message': '{failing_message}'}}\n",
        encoding="utf-8",
    )
    (repo_root / "tests" / "test_app.py").write_text(
        "import unittest\n"
        "from src.app import login\n\n"
        "class LoginTest(unittest.TestCase):\n"
        "    def test_login(self):\n"
        "        self.assertEqual(login('demo', 'secret')['message'], 'baseline')\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )


def write_ts_repo(
    repo_root: pathlib.Path,
    *,
    scripts: dict[str, str] | None = None,
    deps: dict[str, str] | None = None,
    dev_deps: dict[str, str] | None = None,
    test_dir: str = "tests",
    include_python_script: bool = False,
    package_manager: str | None = None,
) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / test_dir).mkdir(parents=True, exist_ok=True)
    package_payload = {
        "name": "stage18-ts",
        "private": True,
        "type": "module",
        "scripts": scripts or {"test": "node --test"},
        "dependencies": deps or {},
        "devDependencies": dev_deps or {},
    }
    if package_manager:
        package_payload["packageManager"] = package_manager
    (repo_root / "package.json").write_text(json.dumps(package_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (repo_root / "src" / "cli.js").write_text(
        "export function runCommand(name) {\n"
        "  return `baseline:${name}`;\n"
        "}\n",
        encoding="utf-8",
    )
    (repo_root / test_dir / "cli.test.js").write_text(
        "import test from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "import { runCommand } from '../src/cli.js';\n\n"
        "test('runCommand returns a stable label', () => {\n"
        "  assert.equal(runCommand('demo'), 'baseline:demo');\n"
        "});\n",
        encoding="utf-8",
    )
    if include_python_script:
        (repo_root / "scripts").mkdir(parents=True, exist_ok=True)
        (repo_root / "scripts" / "helper.py").write_text("def helper():\n    return 'ok'\n", encoding="utf-8")


def write_multi_function_python_file(repo_root: pathlib.Path, count: int) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    lines = []
    for index in range(count):
        lines.append(f"def fn_{index}():\n    return {index}\n")
    (repo_root / "src" / "multi.py").write_text("\n".join(lines), encoding="utf-8")
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests" / "test_multi.py").write_text(
        "import unittest\n"
        "from src.multi import fn_0\n\n"
        "class MultiTest(unittest.TestCase):\n"
        "    def test_multi(self):\n"
        "        self.assertEqual(fn_0(), 0)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )


class Stage18WorkflowTest(unittest.TestCase):
    def test_primary_adapter_auto_falls_back_to_language_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root)
            config = {
                "primary_adapter": "auto",
                "language_adapter": "tsjs",
                "supplemental_adapters": [],
                "python": {"source_globs": ["scripts/*.py", "scripts/**/*.py"], "test_globs": ["tests/**/*.py"]},
                "tsjs": {"source_globs": ["src/*.js", "src/**/*.js"], "test_globs": ["tests/*.js", "tests/**/*.js"]},
                "graph": {"exclude_dirs": []},
            }
            decision = adapters.effective_adapter_decision(config, repo_root)
            self.assertEqual(decision["primary_adapter"], "tsjs")
            self.assertEqual(decision["adapter_source"], "language_adapter_fallback")

    def test_setup_profile_node_cli_sets_effective_tsjs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root)
            payload = setup_repo(repo_root, profile="node-cli")
            config = read_json(config_path(repo_root))
            self.assertEqual(payload["detect"]["primary_adapter"], "tsjs")
            self.assertEqual(config["primary_adapter"], "tsjs")

    def test_mixed_ts_python_repo_does_not_choose_python_when_language_adapter_tsjs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, include_python_script=True)
            config = {
                "primary_adapter": "auto",
                "language_adapter": "tsjs",
                "supplemental_adapters": [],
                "python": {"source_globs": ["scripts/*.py", "scripts/**/*.py"], "test_globs": ["tests/**/*.py"]},
                "tsjs": {"source_globs": ["src/*.js", "src/**/*.js"], "test_globs": ["tests/*.js", "tests/**/*.js"]},
                "graph": {"exclude_dirs": []},
            }
            decision = adapters.effective_adapter_decision(config, repo_root)
            self.assertEqual(decision["primary_adapter"], "tsjs")
            self.assertIn("python", decision["supplemental_adapters"])

    def test_primary_tsjs_with_supplemental_python_keeps_tsjs_as_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, include_python_script=True)
            config = {
                "primary_adapter": "tsjs",
                "language_adapter": "tsjs",
                "supplemental_adapters": ["python"],
                "python": {"source_globs": ["scripts/*.py", "scripts/**/*.py"], "test_globs": ["tests/**/*.py"]},
                "tsjs": {"source_globs": ["src/*.js", "src/**/*.js"], "test_globs": ["tests/*.js", "tests/**/*.js"]},
                "graph": {"exclude_dirs": []},
            }
            decision = adapters.effective_adapter_decision(config, repo_root)
            self.assertEqual(decision["primary_adapter"], "tsjs")
            self.assertIn("python", decision["supplemental_adapters"])

    def test_repo_config_test_command_overrides_profile_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, scripts={"test": "node --test"})
            config = {"tsjs": {"test_command": ["npm", "run", "test:run"]}}
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config=config,
                adapter_name="tsjs",
                profile_name="node-cli",
            )
            self.assertEqual(payload["selected_test_command"], "npm run test:run")
            self.assertEqual(payload["test_command_source"], "repo_config:tsjs.test_command")

    def test_node_cli_profile_uses_package_json_test_before_node_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, scripts={"test": "vitest run"})
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={},
                adapter_name="tsjs",
                profile_name="node-cli",
            )
            self.assertEqual(payload["selected_test_command"], "npm run test")
            self.assertEqual(payload["test_command_source"], "package_json_script:test")

    def test_vitest_project_uses_npm_run_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, scripts={"test": "vitest run"}, dev_deps={"vitest": "^1.0.0"})
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={},
                adapter_name="tsjs",
                profile_name="react-vite",
            )
            self.assertEqual(payload["selected_test_command"], "npm run test")

    def test_test_run_script_beats_node_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, scripts={"test:run": "vitest run", "test": "node --test"})
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={},
                adapter_name="tsjs",
                profile_name="node-cli",
            )
            self.assertEqual(payload["selected_test_command"], "npm run test:run")
            self.assertEqual(payload["test_command_source"], "package_json_script:test:run")

    def test_bun_project_can_use_bun_test_blueprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(
                repo_root,
                scripts={"test:blueprint": "bun test --run"},
                package_manager="bun@1.1.0",
            )
            (repo_root / "bun.lockb").write_text("", encoding="utf-8")
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={},
                adapter_name="tsjs",
                profile_name="node-cli",
            )
            self.assertEqual(payload["selected_test_command"], "bun run test:blueprint")

    def test_recent_successful_test_command_is_reused_before_profile_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, scripts={"test": "node --test"})
            history_path = repo_root / ".ai" / "codegraph" / "test-command-history.jsonl"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-04-22T00:00:00+00:00",
                        "command": "npm run test:run",
                        "command_argv": ["npm", "run", "test:run"],
                        "source": "repo_config:tsjs.test_command",
                        "status": "passed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            payload = test_command_resolver.resolve_test_command(
                workspace_root=repo_root,
                project_root=repo_root,
                config={},
                adapter_name="tsjs",
                profile_name="node-cli",
            )
            self.assertEqual(payload["selected_test_command"], "npm run test:run")
            self.assertEqual(payload["test_command_source"], "recent_success")

    def test_preflight_flags_sh_script_on_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            script = repo_root / "test-blueprint.sh"
            script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            payload = test_command_resolver.preflight_test_command(["test-blueprint.sh"], repo_root, "windows")
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["issues"][0]["kind"], "shell_script_on_windows")

    def test_preflight_flags_crlf_shell_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            script = repo_root / "test-blueprint.sh"
            script.write_text("#!/usr/bin/env bash\r\necho ok\r\n", encoding="utf-8")
            payload = test_command_resolver.preflight_test_command(["test-blueprint.sh"], repo_root, "windows")
            issue_kinds = {item["kind"] for item in payload["issues"]}
            self.assertIn("crlf_shell_script", issue_kinds)

    def test_finish_distinguishes_baseline_red_from_new_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo(repo_root, failing_message="broken-a")
            setup_repo(repo_root, profile="python-basic")
            analyze_json(repo_root, seed="fn:src/app.py:login", changed_files=["src/app.py"])
            first_finish = run_cig(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
                expect_success=False,
            )
            self.assertNotEqual(first_finish.returncode, 0)
            run_cig_json(
                repo_root,
                "baseline",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--capture-current",
            )
            second_finish = run_cig_json(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
            )
            self.assertEqual(second_finish["tests"]["regression_status"], "no_regression")
            (repo_root / "src" / "app.py").write_text(
                "def login(user_name, password):\n    return {'ok': False, 'message': 'broken-b'}\n",
                encoding="utf-8",
            )
            third_finish = run_cig(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
                expect_success=False,
            )
            self.assertNotEqual(third_finish.returncode, 0)
            results = read_json(repo_root / ".ai" / "codegraph" / "test-results.json")
            self.assertEqual(results["regression_status"], "new_failure")

    def test_finish_handoff_matches_test_results_after_previous_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo(repo_root, failing_message="broken")
            setup_repo(repo_root, profile="python-basic")
            analyze_json(repo_root, seed="fn:src/app.py:login", changed_files=["src/app.py"])
            failed = run_cig(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
                expect_success=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            write_python_repo(repo_root, failing_message="baseline")
            successful = run_cig_json(
                repo_root,
                "finish",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--changed-file",
                "src/app.py",
                "--test-scope",
                "configured",
            )
            handoff_text = (repo_root / ".ai" / "codegraph" / "handoff" / "latest.md").read_text(encoding="utf-8")
            test_results = read_json(repo_root / ".ai" / "codegraph" / "test-results.json")
            self.assertTrue(test_results["tests_passed"])
            self.assertIn("Tests passed: True", handoff_text)
            self.assertNotIn("Tests passed: False", handoff_text)
            self.assertEqual(successful["final_state"]["tests_passed"], test_results["tests_passed"])

    def test_seed_selection_required_writes_nonempty_seed_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_multi_function_python_file(repo_root, 4)
            setup_repo(repo_root, profile="python-basic")
            result = run_cig(
                repo_root,
                "analyze",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--changed-file",
                "src/multi.py",
                expect_success=False,
            )
            self.assertNotEqual(result.returncode, 0)
            seed_candidates = read_json(repo_root / ".ai" / "codegraph" / "seed-candidates.json")
            self.assertEqual(seed_candidates["status"], "selection_required")
            self.assertTrue(seed_candidates["candidates"])

    def test_seed_candidates_match_last_error_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_multi_function_python_file(repo_root, 4)
            setup_repo(repo_root, profile="python-basic")
            run_cig(
                repo_root,
                "analyze",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--changed-file",
                "src/multi.py",
                expect_success=False,
            )
            seed_candidates = read_json(repo_root / ".ai" / "codegraph" / "seed-candidates.json")
            last_error = read_json(repo_root / ".ai" / "codegraph" / "logs" / "last-error.json")
            self.assertEqual(len(seed_candidates["candidates"]), len(last_error["alternatives"]))

    def test_changed_file_priority_beats_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo(repo_root)
            setup_repo(repo_root, profile="python-basic")
            init_git_repo(repo_root)
            (repo_root / "src" / "app.py").write_text("def login(user_name, password):\n    return {'ok': False, 'message': 'dirty'}\n", encoding="utf-8")
            config = read_json(config_path(repo_root))
            config["language_adapter"] = "python"
            write_json(config_path(repo_root), config)
            payload = analyze_json(
                repo_root,
                changed_files=[".zhanggong-impact-blueprint/config.json"],
                extra_args=["--allow-fallback"],
            )
            context = payload["context_resolution"]
            self.assertEqual(context["context_source"], "explicit_changed_file")
            self.assertFalse(context["background_dirty_files_used_for_seed"])
            self.assertGreaterEqual(context["background_dirty_files_count"], 1)

    def test_config_changed_file_generates_config_or_file_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo(repo_root)
            setup_repo(repo_root, profile="python-basic")
            payload = analyze_json(
                repo_root,
                changed_files=[".zhanggong-impact-blueprint/config.json"],
                extra_args=["--allow-fallback"],
            )
            self.assertTrue(payload["seed"].startswith("file:.zhanggong-impact-blueprint/config.json"))

    def test_tsjs_test_directory_singular_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, test_dir="test")
            self.assertEqual(recommend_tests.detect_test_directories(repo_root), ["test"])

    def test_setup_default_is_minimal(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo(repo_root)
            setup_repo(repo_root, profile="python-basic")
            self.assertTrue((repo_root / ".zhanggong-impact-blueprint" / "config.json").exists())
            self.assertTrue((repo_root / ".zhanggong-impact-blueprint" / "schema.sql").exists())
            self.assertTrue((repo_root / ".ai" / "codegraph").exists())
            self.assertFalse((repo_root / "QUICKSTART.md").exists())
            self.assertFalse((repo_root / "AGENTS.md").exists())

    def test_setup_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo(repo_root)
            payload = run_cig_json(
                repo_root,
                "setup",
                "--workspace-root",
                str(repo_root),
                "--project-root",
                ".",
                "--profile",
                "python-basic",
                "--dry-run",
            )
            self.assertEqual(payload["mode"], "minimal")
            self.assertFalse((repo_root / ".zhanggong-impact-blueprint" / "config.json").exists())

    def test_analyze_default_output_is_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_python_repo(repo_root)
            setup_repo(repo_root, profile="python-basic")
            result = run_cig(
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
            )
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            self.assertLessEqual(len(lines), 20)
            self.assertTrue(any(line.startswith("report_path:") for line in lines))
            self.assertTrue(any(line.startswith("next_action_path:") for line in lines))

    def test_fresh_graph_with_dirty_workspace_explains_medium_trust(self):
        axes = trust_policy.trust_axes_payload(
            graph_freshness="fresh",
            generated_noise=True,
            dependency_fingerprint_status="unchanged",
            context_confidence="explicit",
            adapter_confidence="high",
            test_signal="configured",
        )
        self.assertEqual(axes["graph_freshness"], "fresh")
        self.assertEqual(axes["workspace_noise"], "high")
        self.assertIn(axes["overall_trust"], {"medium", "low"})
        self.assertTrue(axes["trust_explanation"])

    def test_multi_seed_auto_allows_small_candidate_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_multi_function_python_file(repo_root, 3)
            setup_repo(repo_root, profile="python-basic")
            payload = analyze_json(repo_root, changed_files=["src/multi.py"])
            self.assertEqual(payload["seed_selection"]["mode"], "multi_seed_auto")
            self.assertEqual(len(payload["secondary_seeds"]), 2)

    def test_calibrate_reports_effective_adapter_and_test_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, scripts={"test:run": "vitest run"}, include_python_script=True)
            setup_repo(repo_root, profile="node-cli")
            payload = run_cig_json(
                repo_root,
                "calibrate",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
            )
            self.assertEqual(payload["adapter"]["primary_adapter"], "tsjs")
            self.assertEqual(payload["test_command"]["selected_test_command"], "npm run test:run")

    def test_calibrate_apply_updates_repo_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = pathlib.Path(tmp)
            write_ts_repo(repo_root, scripts={"test:run": "vitest run"}, include_python_script=True)
            setup_repo(repo_root)
            config = read_json(config_path(repo_root))
            config["primary_adapter"] = "auto"
            config["language_adapter"] = "auto"
            write_json(config_path(repo_root), config)
            run_cig_json(
                repo_root,
                "calibrate",
                "--workspace-root",
                str(repo_root),
                "--config",
                str(config_path(repo_root)),
                "--apply",
            )
            updated = read_json(config_path(repo_root))
            self.assertEqual(updated["primary_adapter"], "tsjs")
            self.assertEqual(updated["tsjs"]["test_command"], ["npm", "run", "test:run"])


if __name__ == "__main__":
    unittest.main()
