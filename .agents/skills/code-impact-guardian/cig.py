#!/usr/bin/env python3
import argparse
import json
import pathlib
import shutil
import subprocess
import sys


SKILL_DIR = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import after_edit_update  # noqa: E402
import build_graph  # noqa: E402
import generate_report  # noqa: E402
import list_seeds  # noqa: E402
from adapters import detect_language_adapter  # noqa: E402
from doc_sources import doc_source_doctor_status  # noqa: E402


DEFAULT_CONFIG = {
    "project_root": ".",
    "language_adapter": "auto",
    "rule_adapter": "markdown",
    "doc_source_adapter": "local_markdown",
    "graph": {
        "db_path": ".ai/codegraph/codegraph.db",
        "report_dir": ".ai/codegraph/reports",
        "build_log_path": ".ai/codegraph/build.log",
        "test_results_path": ".ai/codegraph/test-results.json",
    },
    "rules": {"globs": ["docs/rules/*.md"]},
    "python": {
        "source_globs": ["src/*.py", "src/**/*.py"],
        "test_globs": ["tests/*.py", "tests/**/*.py"],
        "test_command": ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        "coverage_adapter": "coveragepy",
    },
    "tsjs": {
        "source_globs": ["src/*.js", "src/**/*.js", "src/*.ts", "src/**/*.ts"],
        "test_globs": ["tests/*.js", "tests/**/*.js", "tests/*.ts", "tests/**/*.ts"],
        "test_command": ["node", "--test"],
        "coverage_adapter": "unavailable",
    },
    "generic": {
        "source_globs": ["src/*", "src/**/*"],
        "test_command": [],
        "coverage_adapter": "unavailable",
    },
    "impact": {"max_depth": 3},
}


DEFAULT_SCHEMA_TEXT = """PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repo_meta (
  meta_key TEXT PRIMARY KEY,
  meta_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
  node_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('file', 'function', 'test', 'rule')),
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  symbol TEXT,
  start_line INTEGER,
  end_line INTEGER,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  repo_source_id TEXT NOT NULL,
  git_sha TEXT NOT NULL,
  file_path TEXT NOT NULL,
  start_line INTEGER,
  end_line INTEGER,
  diff_ref TEXT,
  blame_ref TEXT,
  permalink TEXT,
  stable_link TEXT,
  extractor TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS edges (
  edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
  src_id TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
  edge_type TEXT NOT NULL CHECK(edge_type IN ('DEFINES', 'CALLS', 'IMPORTS', 'COVERS', 'GOVERNS')),
  dst_id TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
  is_direct INTEGER NOT NULL DEFAULT 1 CHECK(is_direct IN (0, 1)),
  evidence_id TEXT REFERENCES evidence(evidence_id) ON DELETE SET NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(src_id, edge_type, dst_id, is_direct)
);

CREATE TABLE IF NOT EXISTS rule_documents (
  rule_node_id TEXT PRIMARY KEY REFERENCES nodes(node_id) ON DELETE CASCADE,
  markdown_path TEXT NOT NULL,
  frontmatter_json TEXT NOT NULL DEFAULT '{}',
  body_markdown TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS impact_reports (
  report_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  seed_node_id TEXT NOT NULL,
  git_sha TEXT NOT NULL,
  report_path TEXT NOT NULL,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS test_runs (
  run_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  command_json TEXT NOT NULL,
  status TEXT NOT NULL,
  exit_code INTEGER,
  output_path TEXT,
  coverage_path TEXT,
  coverage_status TEXT NOT NULL,
  coverage_reason TEXT,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS coverage_observations (
  observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES test_runs(run_id) ON DELETE CASCADE,
  test_node_id TEXT REFERENCES nodes(node_id) ON DELETE SET NULL,
  target_node_id TEXT REFERENCES nodes(node_id) ON DELETE SET NULL,
  file_path TEXT NOT NULL,
  line_no INTEGER,
  summary_json TEXT NOT NULL DEFAULT '{}',
  raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS task_runs (
  task_run_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  seed_node_id TEXT NOT NULL,
  command_name TEXT NOT NULL,
  detected_adapter TEXT NOT NULL,
  report_path TEXT,
  status TEXT NOT NULL,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS edit_rounds (
  edit_round_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  task_run_id TEXT NOT NULL REFERENCES task_runs(task_run_id) ON DELETE CASCADE,
  round_index INTEGER NOT NULL,
  seed_node_id TEXT NOT NULL,
  changed_files_json TEXT NOT NULL DEFAULT '[]',
  summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_diffs (
  file_diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
  edit_round_id TEXT NOT NULL REFERENCES edit_rounds(edit_round_id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  diff_kind TEXT NOT NULL,
  before_hash TEXT,
  after_hash TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS symbol_diffs (
  symbol_diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
  edit_round_id TEXT NOT NULL REFERENCES edit_rounds(edit_round_id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  symbol_kind TEXT NOT NULL,
  diff_kind TEXT NOT NULL,
  before_symbol TEXT,
  after_symbol TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_evidence_file_path ON evidence(file_path);
CREATE INDEX IF NOT EXISTS idx_test_runs_task ON test_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_edit_rounds_task ON edit_rounds(task_id);
CREATE INDEX IF NOT EXISTS idx_file_diffs_round ON file_diffs(edit_round_id);
CREATE INDEX IF NOT EXISTS idx_symbol_diffs_round ON symbol_diffs(edit_round_id);

INSERT INTO repo_meta(meta_key, meta_value) VALUES
  ('schema_version', '2'),
  ('graph_mode', 'direct-edges-only')
ON CONFLICT(meta_key) DO UPDATE SET meta_value = excluded.meta_value;
"""


def template_root() -> pathlib.Path:
    return SKILL_DIR.parents[2]


def copy_template(source_root: pathlib.Path, destination_root: pathlib.Path) -> None:
    ignore = shutil.ignore_patterns(".git", ".ai", "__pycache__", "*.pyc", "dist", "*.zip")
    if destination_root.exists():
        shutil.rmtree(destination_root)
    shutil.copytree(source_root, destination_root, ignore=ignore)


def init_git_repo(workspace_root: pathlib.Path) -> None:
    subprocess.run(["git", "init"], cwd=workspace_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Code Impact Guardian Demo"], cwd=workspace_root, check=True)
    subprocess.run(["git", "config", "user.email", "demo@example.invalid"], cwd=workspace_root, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=workspace_root, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initialize demo workspace"], cwd=workspace_root, check=True, capture_output=True, text=True)


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def config_path_for(workspace_root: pathlib.Path) -> pathlib.Path:
    return workspace_root / ".code-impact-guardian" / "config.json"


def schema_path_for(workspace_root: pathlib.Path) -> pathlib.Path:
    return workspace_root / ".code-impact-guardian" / "schema.sql"


def default_config_payload() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def default_schema_text() -> str:
    source_schema = template_root() / ".code-impact-guardian" / "schema.sql"
    if source_schema.exists():
        return source_schema.read_text(encoding="utf-8")
    return DEFAULT_SCHEMA_TEXT


def init_workspace(workspace_root: pathlib.Path) -> dict:
    codegraph_dir = workspace_root / ".ai" / "codegraph"
    report_dir = codegraph_dir / "reports"
    config_dir = workspace_root / ".code-impact-guardian"
    config_dir.mkdir(parents=True, exist_ok=True)
    codegraph_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_path_for(workspace_root)
    schema_path = schema_path_for(workspace_root)
    created: list[str] = []

    if not config_path.exists():
        write_json(config_path, default_config_payload())
        created.append(str(config_path.relative_to(workspace_root)))
    if not schema_path.exists():
        schema_path.write_text(default_schema_text(), encoding="utf-8")
        created.append(str(schema_path.relative_to(workspace_root)))

    return {
        "workspace_root": str(workspace_root),
        "created": created,
        "config_path": str(config_path),
        "schema_path": str(schema_path),
        "codegraph_dir": str(codegraph_dir),
    }


def set_fixture_config(workspace_root: pathlib.Path, fixture: str, persist: bool) -> pathlib.Path:
    config_path = config_path_for(workspace_root)
    payload = load_json(config_path)
    payload["project_root"] = f"examples/{fixture}"
    payload["language_adapter"] = "auto"
    if persist:
        write_json(config_path, payload)
        return config_path
    temp_config_path = workspace_root / ".ai" / "codegraph" / f"demo-{fixture}-config.json"
    temp_config_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(temp_config_path, payload)
    return temp_config_path


def apply_python_demo_edit(workspace_root: pathlib.Path) -> str:
    target = workspace_root / "examples" / "python_minimal" / "src" / "app.py"
    original = target.read_text(encoding="utf-8")
    if 'DEMO_RELEASE_TRACK = "baseline"' in original:
        updated = original.replace('DEMO_RELEASE_TRACK = "baseline"', 'DEMO_RELEASE_TRACK = "edited-by-demo"')
    elif 'DEMO_RELEASE_TRACK = "edited-by-demo"' in original:
        updated = original.replace('DEMO_RELEASE_TRACK = "edited-by-demo"', 'DEMO_RELEASE_TRACK = "baseline"')
    else:
        raise RuntimeError("Demo edit marker not found in python fixture")
    if updated == original:
        raise RuntimeError("Python demo edit did not change the file")
    target.write_text(updated, encoding="utf-8")
    return "src/app.py"


def apply_tsjs_demo_edit(workspace_root: pathlib.Path) -> str:
    target = workspace_root / "examples" / "tsjs_minimal" / "src" / "math.js"
    original = target.read_text(encoding="utf-8")
    if 'const DEMO_TSJS_TRACK = "baseline";' in original:
        updated = original.replace('const DEMO_TSJS_TRACK = "baseline";', 'const DEMO_TSJS_TRACK = "edited-by-demo";')
    elif 'const DEMO_TSJS_TRACK = "edited-by-demo";' in original:
        updated = original.replace('const DEMO_TSJS_TRACK = "edited-by-demo";', 'const DEMO_TSJS_TRACK = "baseline";')
    else:
        raise RuntimeError("Demo edit marker not found in tsjs fixture")
    if updated == original:
        raise RuntimeError("TS/JS demo edit did not change the file")
    target.write_text(updated, encoding="utf-8")
    return "src/math.js"


def apply_generic_demo_edit(workspace_root: pathlib.Path) -> str:
    target = workspace_root / "examples" / "generic_minimal" / "src" / "settings.conf"
    original = target.read_text(encoding="utf-8")
    if "release_track=baseline" in original:
        updated = original.replace("release_track=baseline", "release_track=edited-by-demo")
    elif "release_track=edited-by-demo" in original:
        updated = original.replace("release_track=edited-by-demo", "release_track=baseline")
    else:
        raise RuntimeError("Demo edit marker not found in generic fixture")
    if updated == original:
        raise RuntimeError("Generic demo edit did not change the file")
    target.write_text(updated, encoding="utf-8")
    return "src/settings.conf"


def fixture_spec(fixture: str) -> dict:
    specs = {
        "python_minimal": {
            "task_id": "demo-login-impact",
            "seed": "fn:src/app.py:login",
            "edit": apply_python_demo_edit,
        },
        "tsjs_minimal": {
            "task_id": "demo-tsjs-impact",
            "seed": "fn:src/math.js:add",
            "edit": apply_tsjs_demo_edit,
        },
        "generic_minimal": {
            "task_id": "demo-generic-impact",
            "seed": "file:src/settings.conf",
            "edit": apply_generic_demo_edit,
        },
    }
    if fixture not in specs:
        raise SystemExit(f"Unsupported fixture: {fixture}")
    return specs[fixture]


def detect_payload(workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    return {
        "workspace_root": str(workspace_root),
        "project_root": str(project_root),
        "configured_adapter": config.get("language_adapter", "auto"),
        "detected_adapter": detect_language_adapter(project_root, config),
    }


def command_available(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def doctor_payload(workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    statuses: list[dict] = []
    overall = "PASS"

    def add_status(level: str, message: str) -> None:
        nonlocal overall
        statuses.append({"level": level, "message": message})
        if level == "FAIL":
            overall = "FAIL"
        elif level == "WARN" and overall != "FAIL":
            overall = "WARN"

    if config_path.exists():
        add_status("PASS", f"config {config_path.relative_to(workspace_root)}")
    else:
        add_status("FAIL", f"config missing at {config_path.relative_to(workspace_root)}")
        return {"overall": overall, "statuses": statuses}

    schema_path = schema_path_for(workspace_root)
    if schema_path.exists():
        add_status("PASS", f"schema {schema_path.relative_to(workspace_root)}")
    else:
        add_status("FAIL", f"schema missing at {schema_path.relative_to(workspace_root)}")
        return {"overall": overall, "statuses": statuses}

    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    if project_root.exists():
        add_status("PASS", f"project_root {project_root}")
    else:
        add_status("FAIL", f"project_root missing: {project_root}")
        return {"overall": overall, "statuses": statuses}

    try:
        detected_adapter = detect_language_adapter(project_root, config)
        add_status("PASS", f"detected_adapter {detected_adapter}")
    except Exception as exc:  # pragma: no cover - defensive
        add_status("FAIL", f"adapter detection failed: {exc}")
        return {"overall": overall, "statuses": statuses}

    git_available = command_available("git")
    if not git_available:
        add_status("WARN", "git command not found; evidence will use UNCOMMITTED markers")
    else:
        try:
            subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=workspace_root, check=True, capture_output=True, text=True)
            add_status("PASS", "git repository available")
        except subprocess.CalledProcessError:
            add_status("WARN", "git repository not initialized in this workspace")

    if detected_adapter == "python":
        add_status("PASS", "python runtime available")
        if command_available("coverage"):
            add_status("PASS", "coverage.py command available")
        else:
            try:
                subprocess.run([sys.executable, "-m", "coverage", "--version"], check=True, capture_output=True, text=True)
                add_status("PASS", "coverage.py module available")
            except subprocess.CalledProcessError:
                add_status("WARN", "coverage.py not available; graph/report still work but coverage import will be unavailable")
    elif detected_adapter == "tsjs":
        if command_available("node"):
            add_status("PASS", "node runtime available")
        else:
            add_status("WARN", "node runtime not found; tsjs test execution will be unavailable")
    else:
        add_status("PASS", "generic fallback available")

    doc_level, doc_message = doc_source_doctor_status(project_root, config)
    add_status(doc_level, doc_message)

    return {"overall": overall, "statuses": statuses}


def print_doctor(payload: dict) -> None:
    print(f"OVERALL {payload['overall']}")
    for status in payload["statuses"]:
        print(f"{status['level']} {status['message']}")


def run_demo(fixture: str, workspace: str | None) -> pathlib.Path:
    source_root = template_root()
    workspace_root = pathlib.Path(workspace).resolve() if workspace else source_root
    if workspace:
        copy_template(source_root, workspace_root)
        init_git_repo(workspace_root)
    else:
        init_workspace(workspace_root)
    config_path = set_fixture_config(workspace_root, fixture, persist=bool(workspace))
    spec = fixture_spec(fixture)
    build_graph.build_graph(workspace_root=workspace_root, config_path=config_path)
    generate_report.generate_report(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=spec["task_id"],
        seed=spec["seed"],
    )
    changed_file = spec["edit"](workspace_root)
    after_edit_update.after_edit_update(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=spec["task_id"],
        seed=spec["seed"],
        changed_files=[changed_file],
    )
    return workspace_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified Code Impact Guardian entry point")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Bootstrap config, schema, and artifact directories")
    init_parser.add_argument("--workspace-root", default=".")

    doctor_parser = subparsers.add_parser("doctor", help="Run a lightweight workspace health check")
    doctor_parser.add_argument("--workspace-root", default=".")
    doctor_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    detect_parser = subparsers.add_parser("detect", help="Detect the active adapter")
    detect_parser.add_argument("--workspace-root", default=".")
    detect_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    build_parser = subparsers.add_parser("build", help="Build or refresh the graph")
    build_parser.add_argument("--workspace-root", default=".")
    build_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    seeds_parser = subparsers.add_parser("seeds", help="List current seeds")
    seeds_parser.add_argument("--workspace-root", default=".")
    seeds_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    report_parser = subparsers.add_parser("report", help="Generate an impact report")
    report_parser.add_argument("--workspace-root", default=".")
    report_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    report_parser.add_argument("--task-id", required=True)
    report_parser.add_argument("--seed", required=True)
    report_parser.add_argument("--max-depth", type=int, default=None)

    after_parser = subparsers.add_parser("after-edit", help="Refresh graph, report, evidence, and tests after an edit")
    after_parser.add_argument("--workspace-root", default=".")
    after_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    after_parser.add_argument("--task-id", required=True)
    after_parser.add_argument("--seed", required=True)
    after_parser.add_argument("--changed-file", action="append", default=[])

    demo_parser = subparsers.add_parser("demo", help="Run a fixture end-to-end demo")
    demo_parser.add_argument("--fixture", choices=["python_minimal", "tsjs_minimal", "generic_minimal"], default="python_minimal")
    demo_parser.add_argument("--workspace", default=None)

    args = parser.parse_args()

    if args.command == "demo":
        workspace_root = run_demo(args.fixture, args.workspace)
        print(workspace_root)
        return 0

    workspace_root = pathlib.Path(args.workspace_root).resolve()

    if args.command == "init":
        print(json.dumps(init_workspace(workspace_root), ensure_ascii=False, indent=2))
        return 0

    config_path = pathlib.Path(getattr(args, "config", ".code-impact-guardian/config.json"))
    if not config_path.is_absolute():
        config_path = (workspace_root / config_path).resolve()

    if args.command == "doctor":
        print_doctor(doctor_payload(workspace_root, config_path))
        return 0
    if args.command == "detect":
        print(json.dumps(detect_payload(workspace_root, config_path), ensure_ascii=False, indent=2))
        return 0
    if args.command == "build":
        print(json.dumps(build_graph.build_graph(workspace_root=workspace_root, config_path=config_path), ensure_ascii=False, indent=2))
        return 0
    if args.command == "seeds":
        print(json.dumps(list_seeds.list_seeds(workspace_root=workspace_root, config_path=config_path), ensure_ascii=False, indent=2))
        return 0
    if args.command == "report":
        print(
            json.dumps(
                generate_report.generate_report(
                    workspace_root=workspace_root,
                    config_path=config_path,
                    task_id=args.task_id,
                    seed=args.seed,
                    max_depth=args.max_depth,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "after-edit":
        print(
            json.dumps(
                after_edit_update.after_edit_update(
                    workspace_root=workspace_root,
                    config_path=config_path,
                    task_id=args.task_id,
                    seed=args.seed,
                    changed_files=args.changed_file,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
