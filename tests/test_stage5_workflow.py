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


class Stage5WorkflowTest(unittest.TestCase):
    def test_sql_postgres_minimal_runs_as_supplemental_adapter(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "code-impact-guardian" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = copy_repo(repo_root, pathlib.Path(tmp) / "stage5-sql-minimal")

            init_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "init",
                    "--workspace-root",
                    str(temp_repo),
                    "--project-root",
                    "examples/sql_pg_minimal",
                    "--with",
                    "sql-postgres",
                ],
                cwd=temp_repo,
            )
            self.assertIn("sql_postgres", init_payload["supplemental_adapters"])

            detect_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "detect",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
            )
            self.assertEqual(detect_payload["primary_adapter"], "generic")
            self.assertEqual(detect_payload["detected_profile"], "generic-file")
            self.assertIn("sql_postgres", detect_payload["supplemental_adapters_detected"])

            doctor_output = subprocess.check_output(
                [
                    sys.executable,
                    str(cig_script),
                    "doctor",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
                text=True,
            )
            self.assertIn("sql_postgres enabled", doctor_output)

            run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "build",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
            )

            seeds_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "seeds",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
            )
            sql_seed = next(
                item
                for item in seeds_payload["function_details"]
                if item["attrs"].get("sql_kind") == "function" and item["symbol"] == "app.issue_session_token"
            )

            report_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "report",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                    "--task-id",
                    "stage5-sql-minimal",
                    "--seed",
                    sql_seed["node_id"],
                ],
                cwd=temp_repo,
            )
            report_text = pathlib.Path(report_payload["report_path"]).read_text(encoding="utf-8")
            self.assertIn("sql_kind", report_text)
            self.assertIn("app.normalize_user_name", report_text)

            sql_file = temp_repo / "examples" / "sql_pg_minimal" / "db" / "functions" / "session.sql"
            original = sql_file.read_text(encoding="utf-8")
            updated = original.replace(
                "-- stage5 demo marker: baseline",
                "-- stage5 demo marker: edited",
            )
            self.assertNotEqual(updated, original)
            sql_file.write_text(updated, encoding="utf-8")

            after_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "after-edit",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                    "--task-id",
                    "stage5-sql-minimal",
                    "--seed",
                    sql_seed["node_id"],
                    "--changed-file",
                    "db/functions/session.sql",
                ],
                cwd=temp_repo,
            )
            self.assertEqual(after_payload["tests"]["status"], "passed")

            with closing(sqlite3.connect(temp_repo / ".ai" / "codegraph" / "codegraph.db")) as conn:
                sql_node = conn.execute(
                    "SELECT attrs_json FROM nodes WHERE node_id = ?",
                    (sql_seed["node_id"],),
                ).fetchone()
                self.assertIsNotNone(sql_node)
                self.assertEqual(json.loads(sql_node[0])["sql_kind"], "function")
                covers_count = conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE edge_type = 'COVERS' AND dst_id = ?",
                    (sql_seed["node_id"],),
                ).fetchone()[0]
                self.assertGreaterEqual(covers_count, 1)

    def test_tsjs_sql_compound_merges_primary_and_supplemental_graph(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig_script = repo_root / ".agents" / "skills" / "code-impact-guardian" / "cig.py"

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = copy_repo(repo_root, pathlib.Path(tmp) / "stage5-tsjs-sql")

            init_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "init",
                    "--workspace-root",
                    str(temp_repo),
                    "--profile",
                    "node-cli",
                    "--with",
                    "sql-postgres",
                    "--project-root",
                    "examples/tsjs_pg_compound",
                ],
                cwd=temp_repo,
            )
            self.assertEqual(init_payload["project_profile"], "node-cli")
            self.assertIn("sql_postgres", init_payload["supplemental_adapters"])

            detect_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "detect",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
            )
            self.assertEqual(detect_payload["primary_adapter"], "tsjs")
            self.assertEqual(detect_payload["detected_profile"], "node-cli")
            self.assertIn("sql_postgres", detect_payload["supplemental_adapters_detected"])

            build_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "build",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
            )
            self.assertEqual(build_payload["primary_adapter"], "tsjs")
            self.assertIn("sql_postgres", build_payload["supplemental_adapters_detected"])

            seeds_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "seeds",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=temp_repo,
            )
            app_seed = next(item for item in seeds_payload["function_details"] if item["symbol"] == "fetchSessionLabel")
            sql_seed = next(item for item in seeds_payload["function_details"] if item["symbol"] == "app.get_session_label")
            self.assertEqual(sql_seed["attrs"]["sql_kind"], "function")

            report_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "report",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                    "--task-id",
                    "stage5-tsjs-sql",
                    "--seed",
                    app_seed["node_id"],
                ],
                cwd=temp_repo,
            )
            report_text = pathlib.Path(report_payload["report_path"]).read_text(encoding="utf-8")
            self.assertIn(sql_seed["node_id"], report_text)

            app_file = temp_repo / "examples" / "tsjs_pg_compound" / "src" / "sessionQueries.js"
            original = app_file.read_text(encoding="utf-8")
            updated = original.replace(
                'const DEMO_COMPOUND_TRACK = "baseline";',
                'const DEMO_COMPOUND_TRACK = "edited";',
            )
            self.assertNotEqual(updated, original)
            app_file.write_text(updated, encoding="utf-8")

            after_payload = run_json(
                [
                    sys.executable,
                    str(cig_script),
                    "after-edit",
                    "--workspace-root",
                    str(temp_repo),
                    "--config",
                    str(temp_repo / ".code-impact-guardian" / "config.json"),
                    "--task-id",
                    "stage5-tsjs-sql",
                    "--seed",
                    app_seed["node_id"],
                    "--changed-file",
                    "src/sessionQueries.js",
                ],
                cwd=temp_repo,
            )
            self.assertEqual(after_payload["tests"]["status"], "passed")

            with closing(sqlite3.connect(temp_repo / ".ai" / "codegraph" / "codegraph.db")) as conn:
                call_count = conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE edge_type = 'CALLS' AND src_id = ? AND dst_id = ?",
                    (app_seed["node_id"], sql_seed["node_id"]),
                ).fetchone()[0]
                tsjs_function_count = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE kind = 'function' AND path LIKE 'src/%'"
                ).fetchone()[0]
                sql_function_count = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE kind = 'function' AND attrs_json LIKE '%\"sql_kind\"%'"
                ).fetchone()[0]
                self.assertGreater(tsjs_function_count, 0)
                self.assertGreater(sql_function_count, 0)
                self.assertGreaterEqual(call_count, 1)


if __name__ == "__main__":
    unittest.main()
