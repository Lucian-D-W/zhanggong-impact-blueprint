import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing


def copy_repo(source_root: pathlib.Path, destination_root: pathlib.Path) -> pathlib.Path:
    ignore = shutil.ignore_patterns(".git", ".ai", "__pycache__", "*.pyc", "dist", "*.zip")
    shutil.copytree(source_root, destination_root, ignore=ignore)
    return destination_root


def run_json(cmd: list[str], cwd: pathlib.Path) -> dict:
    return json.loads(subprocess.check_output(cmd, cwd=cwd, text=True))


class Stage4WorkflowTest(unittest.TestCase):
    def test_node_cli_profile_runs_tsjs_flow_with_real_coverage(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = copy_repo(repo_root, pathlib.Path(tmp) / "stage4-node-cli")

            init_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "init",
                    "--workspace-root",
                    str(temp_repo),
                    "--profile",
                    "node-cli",
                    "--project-root",
                    "examples/tsjs_node_cli",
                ],
                cwd=temp_repo,
            )
            self.assertEqual(init_payload["project_profile"], "node-cli")

            config_payload = json.loads((temp_repo / ".zhanggong-impact-blueprint" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config_payload["project_profile"], "node-cli")
            self.assertEqual(config_payload["project_root"], "examples/tsjs_node_cli")
            self.assertEqual(config_payload["tsjs"]["coverage_adapter"], "v8_family")
            self.assertEqual(config_payload["tsjs"]["test_command"][:3], ["npm", "run", "test:node-cli"])

            detect_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "detect",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
            )
            self.assertEqual(detect_payload["detected_adapter"], "tsjs")
            self.assertEqual(detect_payload["detected_profile"], "node-cli")

            doctor_output = subprocess.check_output(
                [
                    sys.executable,
                    str(cig_script),
                    "doctor",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn("OVERALL PASS", doctor_output)
            self.assertIn("profile node-cli", doctor_output)

            build_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "build",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
            )
            self.assertEqual(build_payload["detected_adapter"], "tsjs")
            self.assertEqual(build_payload["detected_profile"], "node-cli")

            seed_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "seeds",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
            )
            self.assertEqual(seed_payload["detected_profile"], "node-cli")
            self.assertTrue(seed_payload["function_details"])

            run_command_seed = next(
                item for item in seed_payload["function_details"] if item["symbol"] == "runCommand"
            )
            self.assertTrue(run_command_seed["attrs"]["exported"])
            self.assertIn(run_command_seed["attrs"]["definition_kind"], {"function_declaration", "exported_const_arrow"})
            self.assertTrue(run_command_seed["attrs"]["reference_hints"]["exports"])

            report_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "report",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--task-id",
                    "stage4-node-cli",
                    "--seed",
                    run_command_seed["node_id"],
                ],
                cwd=temp_repo,
            )
            report_text = pathlib.Path(report_payload["report_path"]).read_text(encoding="utf-8")
            self.assertIn("Definition metadata", report_text)
            self.assertIn("definition_kind", report_text)
            self.assertIn("Reference hints", report_text)

            target_file = temp_repo / "examples" / "tsjs_node_cli" / "src" / "cli.js"
            original = target_file.read_text(encoding="utf-8")
            updated = original.replace(
                'const DEMO_NODE_CLI_TRACK = "baseline";',
                'const DEMO_NODE_CLI_TRACK = "edited-by-stage4";',
            )
            self.assertNotEqual(updated, original)
            target_file.write_text(updated, encoding="utf-8")

            run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "after-edit",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--task-id",
                    "stage4-node-cli",
                    "--seed",
                    run_command_seed["node_id"],
                    "--changed-file",
                    "src/cli.js",
                ],
                cwd=temp_repo,
            )

            test_results_path = temp_repo / ".ai" / "codegraph" / "test-results.json"
            test_payload = json.loads(test_results_path.read_text(encoding="utf-8"))
            self.assertEqual(test_payload["status"], "passed")
            self.assertEqual(test_payload["coverage_status"], "available")

            with closing(sqlite3.connect(temp_repo / ".ai" / "codegraph" / "codegraph.db")) as conn:
                coverage_rows = conn.execute("SELECT COUNT(*) FROM coverage_observations").fetchone()[0]
                attrs_json = conn.execute(
                    "SELECT attrs_json FROM nodes WHERE node_id = ?",
                    (run_command_seed["node_id"],),
                ).fetchone()[0]
                attrs = json.loads(attrs_json)
                self.assertGreater(coverage_rows, 0)
                self.assertIn("reference_hints", attrs)
                self.assertIn("definition_kind", attrs)

    def test_react_vite_profile_parses_jsx_family_and_keeps_full_flow(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = copy_repo(repo_root, pathlib.Path(tmp) / "stage4-react-vite")

            run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "init",
                    "--workspace-root",
                    str(temp_repo),
                    "--profile",
                    "react-vite",
                    "--project-root",
                    "examples/tsx_react_vite",
                ],
                cwd=temp_repo,
            )

            detect_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "detect",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
            )
            self.assertEqual(detect_payload["detected_adapter"], "tsjs")
            self.assertEqual(detect_payload["detected_profile"], "react-vite")

            doctor_output = subprocess.check_output(
                [
                    sys.executable,
                    str(cig_script),
                    "doctor",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn("OVERALL PASS", doctor_output)
            self.assertIn("profile react-vite", doctor_output)

            run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "build",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
            )

            seed_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "seeds",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                ],
                cwd=temp_repo,
            )
            app_seed = next(item for item in seed_payload["function_details"] if item["symbol"] == "AppShell")
            hook_seed = next(item for item in seed_payload["function_details"] if item["symbol"] == "useGreeting")
            self.assertEqual(app_seed["attrs"]["definition_kind"], "react_component")
            self.assertTrue(app_seed["attrs"]["is_component"])
            self.assertEqual(hook_seed["attrs"]["definition_kind"], "custom_hook")
            self.assertTrue(hook_seed["attrs"]["is_hook"])

            report_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "report",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--task-id",
                    "stage4-react-vite",
                    "--seed",
                    app_seed["node_id"],
                ],
                cwd=temp_repo,
            )
            report_text = pathlib.Path(report_payload["report_path"]).read_text(encoding="utf-8")
            self.assertIn("react_component", report_text)
            self.assertIn("Reference hints", report_text)
            self.assertIn("Direct Impact", report_text)

            target_file = temp_repo / "examples" / "tsx_react_vite" / "src" / "AppShell.tsx"
            original = target_file.read_text(encoding="utf-8")
            updated = original.replace(
                'const DEMO_REACT_VITE_TRACK = "baseline";',
                'const DEMO_REACT_VITE_TRACK = "edited-by-stage4";',
            )
            self.assertNotEqual(updated, original)
            target_file.write_text(updated, encoding="utf-8")

            run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "after-edit",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".zhanggong-impact-blueprint" / "config.json"),
                    "--task-id",
                    "stage4-react-vite",
                    "--seed",
                    app_seed["node_id"],
                    "--changed-file",
                    "src/AppShell.tsx",
                ],
                cwd=temp_repo,
            )

            test_results_path = temp_repo / ".ai" / "codegraph" / "test-results.json"
            test_payload = json.loads(test_results_path.read_text(encoding="utf-8"))
            self.assertEqual(test_payload["status"], "passed")
            self.assertEqual(test_payload["coverage_status"], "available")


if __name__ == "__main__":
    unittest.main()

