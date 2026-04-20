import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from tests.test_stage7_workflow import (
    copy_single_skill_folder,
    run_json,
    write_generic_repo,
    write_python_repo,
)
from tests.test_stage9_workflow import copy_benchmark, git_baseline


def copy_example(repo_root: pathlib.Path, example_name: str) -> None:
    source = pathlib.Path(__file__).resolve().parents[1] / "examples" / example_name
    shutil.copytree(source, repo_root, dirs_exist_ok=True)


class Stage10WorkflowTest(unittest.TestCase):
    def test_skill_structure_and_export_modes_are_normalized(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        skill_root = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint"
        cig_script = skill_root / "cig.py"

        self.assertTrue((skill_root / "assets" / "templates" / "AGENTS.template.md").exists())
        self.assertTrue((skill_root / "assets" / "templates" / "QUICKSTART.template.md").exists())
        self.assertTrue((skill_root / "assets" / "templates" / "CONSUMER_GUIDE.template.md").exists())
        self.assertTrue((skill_root / "assets" / "templates" / "TROUBLESHOOTING.template.md").exists())
        self.assertTrue((skill_root / "references" / "operations.md").exists())
        self.assertTrue((skill_root / "references" / "trust-model.md").exists())
        self.assertTrue((skill_root / "references" / "troubleshooting.md").exists())
        self.assertTrue((skill_root / "references" / "supported-modes.md").exists())
        self.assertTrue((skill_root / "agents" / "openai.yaml").exists())
        self.assertFalse((skill_root / "templates").exists())

        with tempfile.TemporaryDirectory() as tmp:
            consumer_export = pathlib.Path(tmp) / "consumer-export"
            consumer_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(repo_root),
                    "--out",
                    str(consumer_export),
                    "--mode",
                    "consumer",
                ],
                cwd=repo_root,
            )
            self.assertEqual(consumer_payload["mode"], "consumer")
            self.assertTrue((consumer_export / ".agents" / "skills" / "zhanggong-impact-blueprint" / "SKILL.md").exists())
            self.assertTrue((consumer_export / "AGENTS.template.md").exists())
            self.assertTrue((consumer_export / ".zhanggong-impact-blueprint" / "config.template.json").exists())
            self.assertFalse((consumer_export / ".ai").exists())
            self.assertFalse((consumer_export / "tests").exists())
            self.assertFalse((consumer_export / "examples").exists())
            self.assertFalse((consumer_export / "benchmark").exists())
            self.assertFalse((consumer_export / "dist").exists())

            debug_export = pathlib.Path(tmp) / "debug-export"
            debug_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(repo_root),
                    "--out",
                    str(debug_export),
                    "--mode",
                    "debug-bundle",
                ],
                cwd=repo_root,
            )
            self.assertEqual(debug_payload["mode"], "debug-bundle")
            self.assertTrue((debug_export / ".agents" / "skills" / "zhanggong-impact-blueprint" / "SKILL.md").exists())
            self.assertTrue((debug_export / "debug-bundle" / ".ai" / "codegraph").exists())

    def test_python_class_methods_are_seeded_reported_and_finished(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

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

            repo = pathlib.Path(tmp) / "python-oop"
            repo_cig = copy_single_skill_folder(single_export, repo)
            copy_example(repo, "python_oop_minimal")
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "analyze",
                    "--workspace-root",
                    str(repo),
                    "--changed-file",
                    "src/service.py",
                    "--changed-line",
                    "src/service.py:6",
                ],
                cwd=repo,
            )
            self.assertTrue((repo / ".zhanggong-impact-blueprint" / "config.json").exists())
            self.assertEqual(analyze_payload["seed"], "fn:src/service.py:UserService.validate_token")

            seeds_payload = run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "seeds",
                    "--workspace-root",
                    str(repo),
                    "--config",
                    str(repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=repo,
            )
            seed_ids = {item["node_id"] for item in seeds_payload["function_details"]}
            self.assertIn("fn:src/service.py:UserService.validate_token", seed_ids)
            self.assertIn("fn:src/service.py:UserService.normalize_token", seed_ids)

            report_json = json.loads(pathlib.Path(analyze_payload["report"]["json_report_path"]).read_text(encoding="utf-8"))
            self.assertIn(
                {"src": "fn:src/service.py:UserService.validate_token", "edge_type": "CALLS", "dst": "fn:src/service.py:UserService.normalize_token"},
                report_json["direct"]["downstream"],
            )
            self.assertIn("test:tests/test_service.py:TokenFlowTest.test_validate_token", report_json["direct"]["tests"])
            self.assertIn("rule:python-oop-token", report_json["direct"]["rules"])

            service_path = repo / "src" / "service.py"
            service_path.write_text(
                service_path.read_text(encoding="utf-8").replace('return normalized == "demo"', 'return normalized in {"demo"}'),
                encoding="utf-8",
            )
            finish_payload = run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "finish",
                    "--workspace-root",
                    str(repo),
                    "--config",
                    str(repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--changed-file",
                    "src/service.py",
                ],
                cwd=repo,
            )
            self.assertEqual(finish_payload["tests"]["status"], "passed")
            self.assertTrue(finish_payload["brief"]["test_signal"]["affected_tests_found"])

    def test_tsjs_brace_edge_cases_do_not_break_boundaries(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

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

            repo = pathlib.Path(tmp) / "brace-edge-cases"
            repo_cig = copy_single_skill_folder(single_export, repo)
            copy_example(repo, "tsjs_brace_edge_cases")
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
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "analyze",
                    "--workspace-root",
                    str(repo),
                    "--config",
                    str(repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--changed-file",
                    "src/brace.ts",
                    "--changed-line",
                    "src/brace.ts:4",
                ],
                cwd=repo,
            )
            self.assertEqual(analyze_payload["seed"], "fn:src/brace.ts:renderMessage")
            seeds_payload = run_json(
                [
                    sys.executable,
                    str(repo_cig),
                    "seeds",
                    "--workspace-root",
                    str(repo),
                    "--config",
                    str(repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=repo,
            )
            details = {item["node_id"]: item for item in seeds_payload["function_details"]}
            self.assertIn("fn:src/brace.ts:renderMessage", details)
            self.assertIn("fn:src/brace.ts:formatPayload", details)
            self.assertLess(details["fn:src/brace.ts:renderMessage"]["end_line"], details["fn:src/brace.ts:formatPayload"]["start_line"])
            self.assertFalse(details["fn:src/brace.ts:renderMessage"]["attrs"].get("parser_warning"))

            report_json = json.loads(pathlib.Path(analyze_payload["report"]["json_report_path"]).read_text(encoding="utf-8"))
            downstream = {(item["src"], item["dst"]) for item in report_json["direct"]["downstream"]}
            self.assertIn(("fn:src/brace.ts:renderMessage", "fn:src/brace.ts:formatPayload"), downstream)

    def test_non_git_missing_context_errors_cleanly_and_auto_setup_runs(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

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

            repo = pathlib.Path(tmp) / "non-git-missing-context"
            repo_cig = copy_single_skill_folder(single_export, repo)
            write_python_repo(repo)

            analyze_run = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "analyze",
                    "--workspace-root",
                    str(repo),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(analyze_run.returncode, 0)
            self.assertIn("CONTEXT_MISSING", analyze_run.stderr)
            self.assertTrue((repo / ".zhanggong-impact-blueprint" / "config.json").exists())
            self.assertTrue((repo / "AGENTS.md").exists())

            reports_dir = repo / ".ai" / "codegraph" / "reports"
            impact_reports = list(reports_dir.glob("impact-*.md")) if reports_dir.exists() else []
            self.assertFalse(impact_reports)

            last_error = json.loads((repo / ".ai" / "codegraph" / "logs" / "last-error.json").read_text(encoding="utf-8"))
            self.assertEqual(last_error["error_code"], "CONTEXT_MISSING")
            self.assertIn("--changed-file", last_error["suggested_next_step"])
            self.assertIn("--patch-file", last_error["suggested_next_step"])
            self.assertIn("git init", last_error["suggested_next_step"])
            self.assertIn("--allow-fallback", last_error["suggested_next_step"])

    def test_stale_trust_recent_task_bias_and_test_signal_warnings(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

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

            ambiguous_repo = pathlib.Path(tmp) / "recent-task-bias"
            ambiguous_cig = copy_single_skill_folder(single_export, ambiguous_repo)
            copy_benchmark(ambiguous_repo, "ambiguous_multifile")
            run_json(
                [
                    sys.executable,
                    str(ambiguous_cig),
                    "setup",
                    "--workspace-root",
                    str(ambiguous_repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "node-cli",
                ],
                cwd=ambiguous_repo,
            )
            git_baseline(ambiguous_repo)
            auth_path = ambiguous_repo / "src" / "auth.ts"
            auth_path.write_text(auth_path.read_text(encoding="utf-8").replace("openSession(userId)", "openSession(`auth:${userId}`)"), encoding="utf-8")
            first_analyze = run_json(
                [
                    sys.executable,
                    str(ambiguous_cig),
                    "analyze",
                    "--workspace-root",
                    str(ambiguous_repo),
                    "--config",
                    str(ambiguous_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--changed-file",
                    "src/auth.ts",
                    "--changed-line",
                    "src/auth.ts:3",
                ],
                cwd=ambiguous_repo,
            )
            self.assertEqual(first_analyze["seed"], "fn:src/auth.ts:login")

            subprocess.run(["git", "add", "."], cwd=ambiguous_repo, check=True)
            subprocess.run(["git", "commit", "-m", "auth change"], cwd=ambiguous_repo, check=True, capture_output=True, text=True)

            session_path = ambiguous_repo / "src" / "session.ts"
            session_path.write_text(session_path.read_text(encoding="utf-8").replace("session:", "session-v2:"), encoding="utf-8")
            second_analyze = run_json(
                [
                    sys.executable,
                    str(ambiguous_cig),
                    "analyze",
                    "--workspace-root",
                    str(ambiguous_repo),
                    "--config",
                    str(ambiguous_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--changed-file",
                    "src/session.ts",
                    "--changed-line",
                    "src/session.ts:2",
                ],
                cwd=ambiguous_repo,
            )
            self.assertEqual(second_analyze["seed"], "fn:src/session.ts:openSession")
            top_candidates = second_analyze["seed_selection"]["top_candidates"]
            self.assertLessEqual(len(top_candidates), 3)
            self.assertTrue(
                any(detail.lower().startswith("changed-line hits") or detail.lower().startswith("changed-line is near") for detail in top_candidates[0]["reason_details"])
            )

            manifest_path = ambiguous_repo / ".ai" / "codegraph" / "build-manifest.json"
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload["timestamp"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            stale_build = run_json(
                [
                    sys.executable,
                    str(ambiguous_cig),
                    "build",
                    "--workspace-root",
                    str(ambiguous_repo),
                    "--config",
                    str(ambiguous_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=ambiguous_repo,
            )
            self.assertNotEqual(stale_build["build_decision"]["graph_trust"], "high")
            self.assertIn("GRAPH_TTL_EXCEEDED", stale_build["build_decision"]["reason_codes"])

            generic_repo = pathlib.Path(tmp) / "generic-test-signal"
            generic_cig = copy_single_skill_folder(single_export, generic_repo)
            write_generic_repo(generic_repo)
            run_json(
                [
                    sys.executable,
                    str(generic_cig),
                    "setup",
                    "--workspace-root",
                    str(generic_repo),
                    "--project-root",
                    ".",
                ],
                cwd=generic_repo,
            )
            config_path = generic_repo / ".zhanggong-impact-blueprint" / "config.json"
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            config_payload["generic"]["test_command"] = [sys.executable, "-c", "print('generic ok')"]
            config_path.write_text(json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(generic_cig),
                    "analyze",
                    "--workspace-root",
                    str(generic_repo),
                    "--config",
                    str(config_path),
                    "--changed-file",
                    "src/settings.workflow",
                    "--allow-fallback",
                ],
                cwd=generic_repo,
            )
            settings_path = generic_repo / "src" / "settings.workflow"
            settings_path.write_text("release_track=stage10\n", encoding="utf-8")
            finish_payload = run_json(
                [
                    sys.executable,
                    str(generic_cig),
                    "finish",
                    "--workspace-root",
                    str(generic_repo),
                    "--config",
                    str(config_path),
                    "--changed-file",
                    "src/settings.workflow",
                    "--allow-fallback",
                ],
                cwd=generic_repo,
            )
            self.assertEqual(finish_payload["tests"]["status"], "passed")
            self.assertFalse(finish_payload["brief"]["test_signal"]["affected_tests_found"])
            next_action = json.loads((generic_repo / ".ai" / "codegraph" / "next-action.json").read_text(encoding="utf-8"))
            self.assertEqual(next_action["recommended_action"], "continue_with_warning")
            self.assertIn("no directly affected tests", next_action["suggested_next_step"].lower())


if __name__ == "__main__":
    unittest.main()

