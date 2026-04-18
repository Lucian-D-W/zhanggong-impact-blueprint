import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_stage7_workflow import copy_single_skill_folder, run_json, write_python_repo


def copy_benchmark(repo_root: pathlib.Path, benchmark_name: str) -> None:
    source = pathlib.Path(__file__).resolve().parents[1] / "benchmark" / benchmark_name
    shutil.copytree(source, repo_root, dirs_exist_ok=True)


def git_baseline(repo_root: pathlib.Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Code Impact Guardian"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "cig@example.invalid"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo_root, check=True, capture_output=True, text=True)


class Stage9WorkflowTest(unittest.TestCase):
    def test_context_inference_and_finish_reduce_manual_inputs(self):
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

            python_repo = pathlib.Path(tmp) / "python-stage9"
            python_cig = copy_single_skill_folder(single_export, python_repo)
            write_python_repo(python_repo)
            run_json(
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
            git_baseline(python_repo)
            app_path = python_repo / "src" / "app.py"
            app_path.write_text(app_path.read_text(encoding="utf-8").replace("'baseline'", "'edited-stage9'"), encoding="utf-8")

            analyze_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "analyze",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=python_repo,
            )
            self.assertEqual(analyze_payload["seed"], "fn:src/app.py:login")
            self.assertEqual(analyze_payload["report"]["mode"], "brief")
            self.assertEqual(analyze_payload["brief"]["selected_seed"], analyze_payload["seed"])
            self.assertIn("src/app.py", analyze_payload["context_resolution"]["changed_files"])
            self.assertTrue(pathlib.Path(analyze_payload["machine_outputs"]["context_resolution_path"]).exists())
            self.assertTrue(pathlib.Path(analyze_payload["machine_outputs"]["seed_candidates_path"]).exists())
            self.assertTrue(pathlib.Path(analyze_payload["machine_outputs"]["next_action_path"]).exists())
            report_text = pathlib.Path(analyze_payload["report"]["report_path"]).read_text(encoding="utf-8")
            self.assertIn("# Impact Brief", report_text)

            app_path.write_text(app_path.read_text(encoding="utf-8").replace("'edited-stage9'", "'finished-stage9'"), encoding="utf-8")
            finish_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "finish",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=python_repo,
            )
            self.assertEqual(finish_payload["seed"], analyze_payload["seed"])
            self.assertEqual(finish_payload["tests"]["status"], "passed")
            self.assertEqual(finish_payload["brief"]["selected_seed"], analyze_payload["seed"])

    def test_benchmark_repos_cover_tsjs_react_sql_and_generated_noise(self):
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

            tsjs_repo = pathlib.Path(tmp) / "tsjs-medium"
            tsjs_cig = copy_single_skill_folder(single_export, tsjs_repo)
            copy_benchmark(tsjs_repo, "tsjs_medium")
            run_json(
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
            git_baseline(tsjs_repo)
            task_path = tsjs_repo / "src" / "commands" / "runTask.ts"
            task_path.write_text(task_path.read_text(encoding="utf-8").replace("formatTask(flags.name, flags.verbose)", "formatTask(flags.name, true)"), encoding="utf-8")
            tsjs_analyze = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "analyze",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=tsjs_repo,
            )
            self.assertEqual(tsjs_analyze["seed"], "fn:src/commands/runTask.ts:runTask")
            self.assertIn("build_mode", tsjs_analyze["build"]["build_decision"])
            self.assertTrue(tsjs_analyze["brief"]["build_trust_summary"]["reason_codes"])

            react_sql_repo = pathlib.Path(tmp) / "react-sql"
            react_sql_cig = copy_single_skill_folder(single_export, react_sql_repo)
            copy_benchmark(react_sql_repo, "react_sql")
            run_json(
                [
                    sys.executable,
                    str(react_sql_cig),
                    "setup",
                    "--workspace-root",
                    str(react_sql_repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "react-vite",
                    "--with",
                    "sql-postgres",
                ],
                cwd=react_sql_repo,
            )
            git_baseline(react_sql_repo)
            db_client_path = react_sql_repo / "src" / "dbClient.ts"
            db_client_path.write_text(db_client_path.read_text(encoding="utf-8").replace("return sql;", "return `${sql} -- updated`;"), encoding="utf-8")
            react_sql_analyze = run_json(
                [
                    sys.executable,
                    str(react_sql_cig),
                    "analyze",
                    "--workspace-root",
                    str(react_sql_repo),
                    "--config",
                    str(react_sql_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=react_sql_repo,
            )
            self.assertEqual(react_sql_analyze["seed"], "fn:src/dbClient.ts:refreshDashboard")
            report_json = json.loads(pathlib.Path(react_sql_analyze["report"]["json_report_path"]).read_text(encoding="utf-8"))
            self.assertIn("confirmed_edges", report_json["relationships"])
            self.assertIn("high_confidence_hints", report_json["relationships"])
            self.assertIn("metadata_only", report_json["relationships"])

            noise_repo = pathlib.Path(tmp) / "generated-noise"
            noise_cig = copy_single_skill_folder(single_export, noise_repo)
            copy_benchmark(noise_repo, "generated_noise")
            run_json(
                [
                    sys.executable,
                    str(noise_cig),
                    "setup",
                    "--workspace-root",
                    str(noise_repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "node-cli",
                ],
                cwd=noise_repo,
            )
            git_baseline(noise_repo)
            src_path = noise_repo / "src" / "cli.ts"
            src_path.write_text(src_path.read_text(encoding="utf-8").replace("label:", "daily:"), encoding="utf-8")
            dist_path = noise_repo / "dist" / "bundle.js"
            dist_path.write_text('console.log("changed bundle");\n', encoding="utf-8")
            noise_analyze = run_json(
                [
                    sys.executable,
                    str(noise_cig),
                    "analyze",
                    "--workspace-root",
                    str(noise_repo),
                    "--config",
                    str(noise_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=noise_repo,
            )
            self.assertIn("GENERATED_OR_CACHE_NOISE_PRESENT", noise_analyze["build"]["build_decision"]["reason_codes"])
            self.assertIn("dist/bundle.js", noise_analyze["context_resolution"]["changed_files"])

    def test_patch_file_ambiguity_surfaces_candidates_and_recovery_files(self):
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

            repo = pathlib.Path(tmp) / "ambiguous"
            repo_cig = copy_single_skill_folder(single_export, repo)
            copy_benchmark(repo, "ambiguous_multifile")
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
                    "node-cli",
                ],
                cwd=repo,
            )
            git_baseline(repo)
            auth_path = repo / "src" / "auth.ts"
            session_path = repo / "src" / "session.ts"
            auth_path.write_text(auth_path.read_text(encoding="utf-8").replace("openSession(userId)", "openSession(`user:${userId}`)"), encoding="utf-8")
            session_path.write_text(session_path.read_text(encoding="utf-8").replace("session:", "session-v2:"), encoding="utf-8")
            patch_path = repo / "changes.patch"
            patch_path.write_text(
                subprocess.check_output(["git", "diff", "--unified=0"], cwd=repo, text=True),
                encoding="utf-8",
            )
            analyze_run = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "analyze",
                    "--workspace-root",
                    str(repo),
                    "--config",
                    str(repo / ".code-impact-guardian" / "config.json"),
                    "--patch-file",
                    str(patch_path),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(analyze_run.returncode, 0)
            self.assertIn("SEED_SELECTION_REQUIRED", analyze_run.stderr)

            context_resolution = json.loads((repo / ".ai" / "codegraph" / "context-resolution.json").read_text(encoding="utf-8"))
            seed_candidates = json.loads((repo / ".ai" / "codegraph" / "seed-candidates.json").read_text(encoding="utf-8"))
            last_error = json.loads((repo / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertIn("patch_file", context_resolution["context_sources"])
            self.assertLessEqual(len(seed_candidates["candidates"]), 3)
            self.assertEqual(last_error["error_code"], "SEED_SELECTION_REQUIRED")
            self.assertIn("--seed", last_error["suggested_next_step"])


if __name__ == "__main__":
    unittest.main()
