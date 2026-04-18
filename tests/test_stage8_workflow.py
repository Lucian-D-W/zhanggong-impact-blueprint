import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests.test_stage7_workflow import (
    copy_single_skill_folder,
    run_json,
    write_generic_repo,
    write_python_repo,
    write_tsjs_repo,
    write_tsjs_sql_repo,
)


def write_react_vite_repo(repo_root: pathlib.Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "rules").mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        json.dumps(
            {
                "name": "stage8-react-vite",
                "private": True,
                "type": "module",
                "dependencies": {"react": "^18.0.0"},
                "devDependencies": {"vite": "^5.0.0"},
                "scripts": {"test:react-vite": "node --test"},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "AppShell.tsx").write_text(
        "export function useGreeting(name: string) {\n"
        "  return `hello:${name}`;\n"
        "}\n\n"
        "export const AppShell = ({ name }: { name: string }) => {\n"
        "  const message = useGreeting(name);\n"
        "  return <div>{message}</div>;\n"
        "};\n",
        encoding="utf-8",
    )
    (repo_root / "tests" / "appshell.test.js").write_text(
        "import test from 'node:test';\n"
        "import assert from 'node:assert/strict';\n\n"
        "test('react vite smoke test stays green', () => {\n"
        "  assert.equal(1, 1);\n"
        "});\n",
        encoding="utf-8",
    )
    (repo_root / "docs" / "rules" / "react.md").write_text(
        "---\n"
        "id: react-shell\n"
        "governs:\n"
        "  - fn:src/AppShell.tsx:AppShell\n"
        "---\n\n"
        "App shell component output must stay stable.\n",
        encoding="utf-8",
    )


class Stage8WorkflowTest(unittest.TestCase):
    def test_daily_driver_analyze_finish_prefers_brief_and_smarter_seed_selection(self):
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

            python_repo = pathlib.Path(tmp) / "python-daily-driver"
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
            analyze_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "analyze",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/app.py",
                    "--changed-line",
                    "src/app.py:4",
                ],
                cwd=python_repo,
            )
            self.assertEqual(analyze_payload["seed"], "fn:src/app.py:login")
            self.assertGreaterEqual(analyze_payload["seed_selection"]["confidence"], 0.8)
            self.assertIn("line", analyze_payload["seed_selection"]["reason"].lower())
            self.assertEqual(analyze_payload["report"]["mode"], "brief")
            self.assertTrue(analyze_payload["report"]["json_report_path"].endswith(".json"))
            self.assertIn(analyze_payload["build"]["build_mode"], {"full", "incremental", "reused"})

            app_path = python_repo / "src" / "app.py"
            app_path.write_text(app_path.read_text(encoding="utf-8").replace("'baseline'", "'edited'"), encoding="utf-8")
            finish_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "finish",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/app.py",
                ],
                cwd=python_repo,
            )
            self.assertEqual(finish_payload["seed"], analyze_payload["seed"])
            self.assertIn(finish_payload["graph"]["build_mode"], {"incremental", "full"})

            status_payload = run_json(
                [
                    sys.executable,
                    str(python_cig),
                    "status",
                    "--workspace-root",
                    str(python_repo),
                    "--config",
                    str(python_repo / ".code-impact-guardian" / "config.json"),
                ],
                cwd=python_repo,
            )
            self.assertEqual(status_payload["mode"], "brief")
            self.assertTrue(status_payload["next_step"])

    def test_react_tsx_and_tsjs_sql_flows_gain_daily_driver_metadata(self):
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

            react_repo = pathlib.Path(tmp) / "react-vite-daily-driver"
            react_cig = copy_single_skill_folder(single_export, react_repo)
            write_react_vite_repo(react_repo)
            run_json(
                [
                    sys.executable,
                    str(react_cig),
                    "setup",
                    "--workspace-root",
                    str(react_repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "react-vite",
                ],
                cwd=react_repo,
            )
            react_analyze = run_json(
                [
                    sys.executable,
                    str(react_cig),
                    "analyze",
                    "--workspace-root",
                    str(react_repo),
                    "--config",
                    str(react_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/AppShell.tsx",
                    "--changed-line",
                    "src/AppShell.tsx:5",
                ],
                cwd=react_repo,
            )
            self.assertEqual(react_analyze["seed"], "fn:src/AppShell.tsx:AppShell")
            self.assertIn("AppShell", json.dumps(react_analyze["seed_selection"], ensure_ascii=False))
            react_report_json = json.loads(pathlib.Path(react_analyze["report"]["json_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(react_report_json["mode"], "brief")
            self.assertIn("top_risks", react_report_json)

            compound_repo = pathlib.Path(tmp) / "tsjs-sql-daily-driver"
            compound_cig = copy_single_skill_folder(single_export, compound_repo)
            write_tsjs_sql_repo(compound_repo)
            run_json(
                [
                    sys.executable,
                    str(compound_cig),
                    "setup",
                    "--workspace-root",
                    str(compound_repo),
                    "--project-root",
                    ".",
                    "--profile",
                    "node-cli",
                    "--with",
                    "sql-postgres",
                ],
                cwd=compound_repo,
            )
            sql_analyze = run_json(
                [
                    sys.executable,
                    str(compound_cig),
                    "analyze",
                    "--workspace-root",
                    str(compound_repo),
                    "--config",
                    str(compound_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "db/functions/001_session.sql",
                    "--changed-line",
                    "db/functions/001_session.sql:10",
                ],
                cwd=compound_repo,
            )
            self.assertTrue(sql_analyze["seed"].startswith("fn:db/functions/001_session.sql:"))
            self.assertGreaterEqual(sql_analyze["seed_selection"]["confidence"], 0.7)
            self.assertLessEqual(len(sql_analyze["seed_selection"]["top_candidates"]), 3)
            sql_report_json = json.loads(pathlib.Path(sql_analyze["report"]["json_report_path"]).read_text(encoding="utf-8"))
            self.assertIn("confirmed_edges", sql_report_json["relationships"])
            self.assertIn("high_confidence_hints", sql_report_json["relationships"])
            self.assertIn("metadata_only", sql_report_json["relationships"])

    def test_incremental_reuse_and_fallback_daily_flow(self):
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

            tsjs_repo = pathlib.Path(tmp) / "tsjs-incremental"
            tsjs_cig = copy_single_skill_folder(single_export, tsjs_repo)
            write_tsjs_repo(tsjs_repo)
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
            first_analyze = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "analyze",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/cli.js",
                    "--changed-line",
                    "src/cli.js:2",
                ],
                cwd=tsjs_repo,
            )
            second_analyze = run_json(
                [
                    sys.executable,
                    str(tsjs_cig),
                    "analyze",
                    "--workspace-root",
                    str(tsjs_repo),
                    "--config",
                    str(tsjs_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/cli.js",
                    "--changed-line",
                    "src/cli.js:2",
                ],
                cwd=tsjs_repo,
            )
            self.assertIn(first_analyze["build"]["build_mode"], {"full", "incremental", "reused"})
            self.assertIn(second_analyze["build"]["build_mode"], {"incremental", "reused"})

            generic_repo = pathlib.Path(tmp) / "generic-fallback-daily"
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
            fallback_analyze = run_json(
                [
                    sys.executable,
                    str(generic_cig),
                    "analyze",
                    "--workspace-root",
                    str(generic_repo),
                    "--config",
                    str(generic_repo / ".code-impact-guardian" / "config.json"),
                    "--changed-file",
                    "src/settings.workflow",
                    "--allow-fallback",
                ],
                cwd=generic_repo,
            )
            self.assertTrue(fallback_analyze["fallback_used"])
            self.assertTrue(fallback_analyze["seed"].startswith("file:"))


if __name__ == "__main__":
    unittest.main()
