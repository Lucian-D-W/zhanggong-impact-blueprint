#!/usr/bin/env python3
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import traceback


SKILL_DIR = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import after_edit_update  # noqa: E402
import build_graph  # noqa: E402
import generate_report  # noqa: E402
import list_seeds  # noqa: E402
from adapters import SQL_POSTGRES_ADAPTER, configured_supplemental_adapters, detect_language_adapter, detect_project_profile_name, detect_supplemental_adapters  # noqa: E402
from doc_sources import doc_source_doctor_status  # noqa: E402
from profiles import AUTO_PROFILE, PROFILE_PRESETS, apply_profile_preset, detect_project_profile, package_json_data, profile_coverage_adapter, profile_test_command  # noqa: E402
from runtime_support import CIGUserError, ensure_runtime_dirs, error_payload_from_exception, event_payload, latest_success_timestamp, normalize_output_paths, read_json, read_jsonl, recent_command_status, runtime_paths, write_error, write_event, write_handoff  # noqa: E402


DEFAULT_CONFIG = {
    "project_root": ".",
    "primary_adapter": "auto",
    "supplemental_adapters": [],
    "language_adapter": "auto",
    "project_profile": "auto",
    "rule_adapter": "markdown",
    "doc_source_adapter": "local_markdown",
    "doc_cache": {
        "enabled": True,
        "dir": ".ai/codegraph/doc-cache",
    },
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
        "source_globs": ["src/*.js", "src/**/*.js", "src/*.ts", "src/**/*.ts", "src/*.jsx", "src/**/*.jsx", "src/*.tsx", "src/**/*.tsx"],
        "test_globs": ["tests/*.js", "tests/**/*.js", "tests/*.ts", "tests/**/*.ts", "tests/*.jsx", "tests/**/*.jsx", "tests/*.tsx", "tests/**/*.tsx"],
        "test_command": ["node", "--test"],
        "coverage_adapter": "v8_family",
    },
    "generic": {
        "source_globs": ["src/*", "src/**/*"],
        "test_command": [],
        "coverage_adapter": "unavailable",
    },
    "rust_lite": {
        "parser_backend": "rust_lite_placeholder",
        "enabled": False,
    },
    "sql_postgres": {
        "enabled": False,
        "source_globs": [
            "db/*.sql",
            "db/**/*.sql",
            "sql/*.sql",
            "sql/**/*.sql",
            "migrations/*.sql",
            "migrations/**/*.sql",
            "supabase/migrations/*.sql",
            "supabase/migrations/**/*.sql"
        ],
        "test_globs": [
            "tests/sql/*.sql",
            "tests/sql/**/*.sql",
            "db/tests/*.sql",
            "db/tests/**/*.sql"
        ],
        "test_command": [
            "python",
            "-c",
            "import pathlib; roots=[pathlib.Path('tests/sql'), pathlib.Path('db/tests')]; files=[]; [files.extend(sorted(root.rglob('*.sql'))) for root in roots if root.exists()]; assert files, 'no SQL test files found'; text='\\n'.join(p.read_text(encoding='utf-8') for p in files).lower(); assert any(token in text for token in ('select ', 'call ', 'perform ')), 'no SQL invocation statements found in SQL tests'"
        ],
        "coverage_adapter": "unavailable",
        "parser_backend": "sql_postgres_lite",
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


def template_asset(name: str) -> pathlib.Path:
    return SKILL_DIR / "templates" / name


def supported_profiles() -> set[str]:
    return set(PROFILE_PRESETS) | {AUTO_PROFILE}


def ensure_supported_profile(profile: str | None) -> None:
    if profile is None or profile in supported_profiles():
        return
    raise CIGUserError(
        "INVALID_PROFILE",
        f"Unsupported profile: {profile}",
        retryable=True,
        suggested_next_step=f"Choose one of: {', '.join(sorted(supported_profiles()))}",
    )


def minimal_gitignore_entries() -> list[str]:
    return [
        ".ai/",
        "__pycache__/",
        "*.pyc",
        ".coverage",
        "coverage-*.json",
        "coverage-*.data",
    ]


def ensure_gitignore(workspace_root: pathlib.Path) -> str:
    gitignore_path = workspace_root / ".gitignore"
    existing_lines: list[str] = []
    if gitignore_path.exists():
        existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    to_append = [entry for entry in minimal_gitignore_entries() if entry not in existing_lines]
    if not gitignore_path.exists():
        gitignore_path.write_text("\n".join(minimal_gitignore_entries()) + "\n", encoding="utf-8")
    elif to_append:
        with gitignore_path.open("a", encoding="utf-8") as fh:
            if existing_lines and existing_lines[-1] != "":
                fh.write("\n")
            for entry in to_append:
                fh.write(f"{entry}\n")
    return str(gitignore_path)


def ensure_agents_md(workspace_root: pathlib.Path) -> str:
    agents_path = workspace_root / "AGENTS.md"
    if not agents_path.exists():
        agents_path.write_text(template_asset("AGENTS.template.md").read_text(encoding="utf-8"), encoding="utf-8")
    return str(agents_path)


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


def normalize_with_adapter(value: str) -> str:
    return value.replace("-", "_")


def init_workspace(
    workspace_root: pathlib.Path,
    *,
    profile: str | None = None,
    project_root: str | None = None,
    with_adapters: list[str] | None = None,
    write_agents_md: bool = False,
    write_gitignore: bool = False,
) -> dict:
    ensure_supported_profile(profile)
    codegraph_dir = workspace_root / ".ai" / "codegraph"
    report_dir = codegraph_dir / "reports"
    doc_cache_dir = codegraph_dir / "doc-cache"
    config_dir = workspace_root / ".code-impact-guardian"
    config_dir.mkdir(parents=True, exist_ok=True)
    codegraph_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    doc_cache_dir.mkdir(parents=True, exist_ok=True)
    ensure_runtime_dirs(workspace_root)

    config_path = config_path_for(workspace_root)
    schema_path = schema_path_for(workspace_root)
    created: list[str] = []

    config_payload = default_config_payload() if not config_path.exists() else load_json(config_path)
    if project_root:
        config_payload["project_root"] = project_root
    config_payload["primary_adapter"] = config_payload.get("primary_adapter", config_payload.get("language_adapter", "auto"))
    config_payload["language_adapter"] = config_payload["primary_adapter"]
    config_payload["supplemental_adapters"] = list(config_payload.get("supplemental_adapters", []))
    if profile and profile != AUTO_PROFILE:
        config_payload = apply_profile_preset(config_payload, profile)
    elif "project_profile" not in config_payload:
        config_payload["project_profile"] = AUTO_PROFILE

    for adapter_name in with_adapters or []:
        normalized = normalize_with_adapter(adapter_name)
        if normalized not in config_payload["supplemental_adapters"]:
            config_payload["supplemental_adapters"].append(normalized)
        if normalized == SQL_POSTGRES_ADAPTER:
            config_payload.setdefault(SQL_POSTGRES_ADAPTER, {})
            config_payload[SQL_POSTGRES_ADAPTER]["enabled"] = True

    resolved_project_root = (workspace_root / config_payload["project_root"]).resolve()
    active_profile = config_payload.get("project_profile", AUTO_PROFILE)
    if active_profile != AUTO_PROFILE:
        if PROFILE_PRESETS.get(active_profile, {}).get("language_adapter") == "tsjs":
            config_payload["tsjs"]["test_command"] = profile_test_command(active_profile, resolved_project_root, config_payload, "tsjs")
            config_payload["tsjs"]["coverage_adapter"] = profile_coverage_adapter(active_profile, config_payload, "tsjs")

    if not config_path.exists():
        write_json(config_path, config_payload)
        created.append(str(config_path.relative_to(workspace_root)))
    else:
        write_json(config_path, config_payload)
    if not schema_path.exists():
        schema_path.write_text(default_schema_text(), encoding="utf-8")
        created.append(str(schema_path.relative_to(workspace_root)))

    agents_md_path = None
    gitignore_path = None
    if write_agents_md:
        agents_md_path = ensure_agents_md(workspace_root)
    if write_gitignore:
        gitignore_path = ensure_gitignore(workspace_root)

    return {
        "workspace_root": str(workspace_root),
        "created": created,
        "config_path": str(config_path),
        "schema_path": str(schema_path),
        "codegraph_dir": str(codegraph_dir),
        "project_profile": config_payload.get("project_profile", AUTO_PROFILE),
        "project_root": config_payload["project_root"],
        "primary_adapter": config_payload["primary_adapter"],
        "supplemental_adapters": config_payload["supplemental_adapters"],
        "agents_md_path": agents_md_path,
        "gitignore_path": gitignore_path,
    }


def set_fixture_config(workspace_root: pathlib.Path, fixture: str, persist: bool) -> pathlib.Path:
    config_path = config_path_for(workspace_root)
    payload = load_json(config_path)
    payload["project_root"] = f"examples/{fixture}"
    payload["primary_adapter"] = "auto"
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


def _toggle_marker(target: pathlib.Path, baseline: str, edited: str, changed_file: str) -> str:
    original = target.read_text(encoding="utf-8")
    if baseline in original:
        updated = original.replace(baseline, edited)
    elif edited in original:
        updated = original.replace(edited, baseline)
    else:
        raise RuntimeError(f"Demo edit marker not found in {target}")
    if updated == original:
        raise RuntimeError(f"Demo edit did not change {target}")
    target.write_text(updated, encoding="utf-8")
    return changed_file


def apply_sql_pg_demo_edit(workspace_root: pathlib.Path) -> str:
    return _toggle_marker(
        workspace_root / "examples" / "sql_pg_minimal" / "db" / "functions" / "session.sql",
        "-- stage5 demo marker: baseline",
        "-- stage5 demo marker: edited",
        "db/functions/session.sql",
    )


def apply_tsjs_pg_demo_edit(workspace_root: pathlib.Path) -> str:
    return _toggle_marker(
        workspace_root / "examples" / "tsjs_pg_compound" / "src" / "sessionQueries.js",
        'const DEMO_COMPOUND_TRACK = "baseline";',
        'const DEMO_COMPOUND_TRACK = "edited";',
        "src/sessionQueries.js",
    )


def fixture_spec(fixture: str) -> dict:
    specs = {
        "python_minimal": {
            "task_id": "demo-login-impact",
            "seed": "fn:src/app.py:login",
            "edit": apply_python_demo_edit,
            "profile": "python-basic",
        },
        "tsjs_minimal": {
            "task_id": "demo-tsjs-impact",
            "seed": "fn:src/math.js:add",
            "edit": apply_tsjs_demo_edit,
            "profile": "node-cli",
        },
        "generic_minimal": {
            "task_id": "demo-generic-impact",
            "seed": "file:src/settings.conf",
            "edit": apply_generic_demo_edit,
            "profile": "generic-file",
        },
        "tsjs_node_cli": {
            "task_id": "demo-node-cli-impact",
            "seed": "fn:src/cli.js:runCommand",
            "edit": lambda root: _toggle_marker(root / "examples" / "tsjs_node_cli" / "src" / "cli.js", 'const DEMO_NODE_CLI_TRACK = "baseline";', 'const DEMO_NODE_CLI_TRACK = "edited-by-demo";', "src/cli.js"),
            "profile": "node-cli",
        },
        "tsx_react_vite": {
            "task_id": "demo-react-vite-impact",
            "seed": "fn:src/AppShell.tsx:AppShell",
            "edit": lambda root: _toggle_marker(root / "examples" / "tsx_react_vite" / "src" / "AppShell.tsx", 'const DEMO_REACT_VITE_TRACK = "baseline";', 'const DEMO_REACT_VITE_TRACK = "edited-by-demo";', "src/AppShell.tsx"),
            "profile": "react-vite",
        },
        "sql_pg_minimal": {
            "task_id": "demo-sql-pg-impact",
            "seed": "fn:db/functions/session.sql:app.issue_session_token",
            "edit": apply_sql_pg_demo_edit,
            "profile": "generic-file",
            "with_adapters": ["sql-postgres"],
        },
        "tsjs_pg_compound": {
            "task_id": "demo-tsjs-pg-impact",
            "seed": "fn:src/sessionQueries.js:fetchSessionLabel",
            "edit": apply_tsjs_pg_demo_edit,
            "profile": "node-cli",
            "with_adapters": ["sql-postgres"],
        },
    }
    if fixture not in specs:
        raise SystemExit(f"Unsupported fixture: {fixture}")
    return specs[fixture]


def detect_payload(workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    detected_adapter = detect_language_adapter(project_root, config)
    detected_profile, confidence, reason = detect_project_profile(project_root, config, detected_adapter)
    supplemental_detected = detect_supplemental_adapters(project_root, config)
    return {
        "workspace_root": str(workspace_root),
        "project_root": str(project_root),
        "primary_adapter": detected_adapter,
        "configured_adapter": config.get("language_adapter", "auto"),
        "configured_primary_adapter": config.get("primary_adapter", config.get("language_adapter", "auto")),
        "configured_profile": config.get("project_profile", AUTO_PROFILE),
        "detected_adapter": detected_adapter,
        "detected_profile": detected_profile,
        "configured_supplemental_adapters": configured_supplemental_adapters(config),
        "supplemental_adapters_detected": supplemental_detected,
        "confidence": confidence,
        "reason": reason,
    }


def default_config_template_payload() -> dict:
    payload = default_config_payload()
    payload["project_root"] = "."
    payload["project_profile"] = AUTO_PROFILE
    payload["primary_adapter"] = "auto"
    payload["language_adapter"] = "auto"
    payload["supplemental_adapters"] = []
    payload["sql_postgres"]["enabled"] = False
    return payload


def export_skill(*, workspace_root: pathlib.Path, out_dir: pathlib.Path) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SKILL_DIR,
        out_dir / ".agents" / "skills" / "code-impact-guardian",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ai", ".git", "dist", "*.zip"),
    )
    package_config_dir = out_dir / ".code-impact-guardian"
    package_config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(schema_path_for(workspace_root), package_config_dir / "schema.sql")
    (package_config_dir / "config.template.json").write_text(
        json.dumps(default_config_template_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(template_asset("AGENTS.template.md"), out_dir / "AGENTS.template.md")
    shutil.copy2(template_asset("QUICKSTART.md"), out_dir / "QUICKSTART.md")
    shutil.copy2(template_asset("TROUBLESHOOTING.md"), out_dir / "TROUBLESHOOTING.md")
    return {
        "status": "exported",
        "out_dir": str(out_dir),
        "exported_files": [
            "AGENTS.template.md",
            "QUICKSTART.md",
            "TROUBLESHOOTING.md",
            ".code-impact-guardian/config.template.json",
            ".code-impact-guardian/schema.sql",
            ".agents/skills/code-impact-guardian/",
        ],
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
        detected_profile, confidence, reason = detect_project_profile(project_root, config, detected_adapter)
        supplemental_detected = detect_supplemental_adapters(project_root, config)
        add_status("PASS", f"detected_adapter {detected_adapter}")
        add_status("PASS", f"profile {detected_profile} ({reason}, confidence={confidence:.2f})")
        if configured_supplemental_adapters(config):
            add_status("PASS", f"supplemental configured: {', '.join(configured_supplemental_adapters(config))}")
        if supplemental_detected:
            add_status("PASS", f"supplemental detected: {', '.join(supplemental_detected)}")
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
            add_status("PASS", "git repository not initialized yet; evidence will use UNCOMMITTED markers until first commit")

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
        package_json = package_json_data(project_root)
        if package_json:
            add_status("PASS", "package.json found")
        else:
            add_status("WARN", "package.json missing; node-cli profile will fall back to direct node commands")
        if detected_profile == "react-vite":
            deps = set(package_json.get("dependencies", {}).keys()) | set(package_json.get("devDependencies", {}).keys())
            if "react" in deps and "vite" in deps:
                add_status("PASS", "react-vite markers found")
            else:
                add_status("WARN", "react-vite profile is selected but package.json is missing react or vite markers")
        elif detected_profile == "next-basic":
            if any((project_root / name).exists() for name in ("next.config.js", "next.config.mjs", "next.config.ts")):
                add_status("PASS", "next markers found")
            else:
                add_status("WARN", "next-basic profile is active but Next markers are missing; TS/JS defaults remain usable while setup is completed")
        elif detected_profile == "electron-renderer":
            if "electron" in (set(package_json.get("dependencies", {}).keys()) | set(package_json.get("devDependencies", {}).keys())):
                add_status("PASS", "electron markers found")
            else:
                add_status("WARN", "electron-renderer profile is active; add electron dependency or renderer markers to fully confirm setup")
        elif detected_profile == "obsidian-plugin":
            if (project_root / "manifest.json").exists():
                add_status("PASS", "obsidian manifest found")
            else:
                add_status("WARN", "obsidian-plugin profile is active; add manifest.json or obsidian dependency to fully confirm setup")
        elif detected_profile == "tauri-frontend":
            if (project_root / "src-tauri").exists():
                add_status("PASS", "tauri markers found")
            else:
                add_status("WARN", "tauri-frontend profile is active; add src-tauri or related markers to fully confirm setup")
    else:
        add_status("PASS", "generic fallback available")

    if SQL_POSTGRES_ADAPTER in configured_supplemental_adapters(config):
        sql_config = config.get(SQL_POSTGRES_ADAPTER, {})
        source_patterns = sql_config.get("source_globs", [])
        test_patterns = sql_config.get("test_globs", [])
        source_files = sum(1 for path in project_root.rglob("*.sql") if any(pathlib.PurePosixPath(path.relative_to(project_root).as_posix()).match(pattern) for pattern in source_patterns))
        test_files = sum(1 for path in project_root.rglob("*.sql") if any(pathlib.PurePosixPath(path.relative_to(project_root).as_posix()).match(pattern) for pattern in test_patterns))
        if source_files == 0 and test_files == 0:
            add_status("FAIL", "sql_postgres enabled but no configured SQL source/test paths were found")
        else:
            add_status("PASS", f"sql_postgres enabled (source_files={source_files}, test_files={test_files})")

    doc_level, doc_message = doc_source_doctor_status(project_root, config)
    add_status(doc_level, doc_message)

    return {"overall": overall, "statuses": statuses}


def print_doctor(payload: dict) -> None:
    print(f"OVERALL {payload['overall']}")
    for status in payload["statuses"]:
        print(f"{status['level']} {status['message']}")


def status_payload(workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    paths = runtime_paths(workspace_root)
    config_exists = config_path.exists()
    config = build_graph.load_config(config_path) if config_exists else {}
    project_root = str(build_graph.project_root_for(workspace_root, config)) if config_exists else None
    events = read_jsonl(paths["events"])
    last_error = read_json(paths["last_error"])
    last_success = latest_success_timestamp(events)
    last_error_timestamp = (last_error or {}).get("timestamp")
    has_unhandled_error = bool(last_error_timestamp and (not last_success or last_error_timestamp > last_success))
    latest_report_path = None
    latest_test_results_path = None
    for item in reversed(events):
        output_paths = item.get("output_paths", {})
        if not latest_report_path and output_paths.get("report_path"):
            latest_report_path = output_paths["report_path"]
        if not latest_test_results_path and output_paths.get("test_results_path"):
            latest_test_results_path = output_paths["test_results_path"]
        if latest_report_path and latest_test_results_path:
            break

    available_seed_count = None
    if config_exists:
        graph = build_graph.graph_paths(workspace_root, config)
        db_path = graph["db_path"]
        if db_path.exists():
            import sqlite3

            with sqlite3.connect(db_path) as conn:
                function_count = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'function'").fetchone()[0]
                file_count = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'file'").fetchone()[0]
                available_seed_count = function_count if function_count else file_count

    return {
        "config_path": str(config_path),
        "config_exists": config_exists,
        "current": {
            "project_root": project_root,
            "project_profile": config.get("project_profile") if config_exists else None,
            "primary_adapter": config.get("primary_adapter", config.get("language_adapter")) if config_exists else None,
            "supplemental_adapters": configured_supplemental_adapters(config) if config_exists else [],
        },
        "recent": {
            "build": recent_command_status(events, "build"),
            "report": recent_command_status(events, "report"),
            "after-edit": recent_command_status(events, "after-edit"),
        },
        "last_error": last_error,
        "latest_report_path": latest_report_path,
        "latest_test_results_path": latest_test_results_path,
        "available_seed_count": available_seed_count or 0,
        "has_unhandled_error": has_unhandled_error,
        "handoff_path": str(paths["handoff_latest"]) if paths["handoff_latest"].exists() else None,
    }


def run_demo(fixture: str, workspace: str | None) -> pathlib.Path:
    source_root = template_root()
    workspace_root = pathlib.Path(workspace).resolve() if workspace else source_root
    spec = fixture_spec(fixture)
    if workspace:
        copy_template(source_root, workspace_root)
        init_git_repo(workspace_root)
    init_workspace(
        workspace_root,
        profile=spec.get("profile"),
        project_root=f"examples/{fixture}",
        with_adapters=spec.get("with_adapters"),
    )
    config_path = set_fixture_config(workspace_root, fixture, persist=bool(workspace))
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


def ensure_config_exists(config_path: pathlib.Path) -> None:
    if not config_path.exists():
        raise CIGUserError(
            "CONFIG_MISSING",
            f"Config file not found: {config_path}",
            retryable=True,
            suggested_next_step="Run `cig.py init --project-root .` before this command.",
        )


def command_context(workspace_root: pathlib.Path, config_path: pathlib.Path | None) -> dict:
    if not config_path or not config_path.exists():
        return {
            "project_root": None,
            "profile": None,
            "primary_adapter": None,
            "supplemental_adapters": [],
        }
    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    primary_adapter = detect_language_adapter(project_root, config)
    detected_profile = detect_project_profile_name(project_root, config, primary_adapter)
    supplemental = detect_supplemental_adapters(project_root, config)
    return {
        "project_root": str(project_root),
        "profile": detected_profile,
        "primary_adapter": primary_adapter,
        "supplemental_adapters": supplemental,
    }


def success_next_step(command_name: str) -> str:
    mapping = {
        "init": "Run `cig.py doctor` next.",
        "doctor": "Run `cig.py detect` next.",
        "detect": "Run `cig.py build` next.",
        "build": "Run `cig.py seeds` next.",
        "seeds": "Pick a seed and run `cig.py report`.",
        "report": "Read the report, edit the code, then run `cig.py after-edit`.",
        "after-edit": "Review the updated report, test results, and handoff note.",
        "demo": "Inspect the generated graph, report, logs, and handoff artifacts.",
        "export-skill": "Copy the exported package into a new repo and run `cig.py init` there.",
        "status": "Inspect the latest error or continue from the suggested next command.",
    }
    return mapping.get(command_name, "Continue with the next workflow step.")


def output_paths_for_command(command_name: str, workspace_root: pathlib.Path, payload: dict | pathlib.Path | None, config_path: pathlib.Path | None) -> dict:
    if command_name == "init":
        return {
            "config_path": payload.get("config_path") if isinstance(payload, dict) else None,
            "schema_path": payload.get("schema_path") if isinstance(payload, dict) else None,
            "agents_md_path": payload.get("agents_md_path") if isinstance(payload, dict) else None,
            "gitignore_path": payload.get("gitignore_path") if isinstance(payload, dict) else None,
        }
    if command_name == "doctor":
        return {}
    if command_name == "detect":
        return {}
    if command_name == "build":
        return {
            "db_path": str(build_graph.graph_paths(workspace_root, build_graph.load_config(config_path))["db_path"]) if config_path and config_path.exists() else None,
            "build_log_path": str(build_graph.graph_paths(workspace_root, build_graph.load_config(config_path))["build_log_path"]) if config_path and config_path.exists() else None,
        }
    if command_name == "report" and isinstance(payload, dict):
        return {"report_path": payload.get("report_path"), "mermaid_path": payload.get("mermaid_path")}
    if command_name == "after-edit" and isinstance(payload, dict):
        return {
            "report_path": payload.get("report", {}).get("report_path"),
            "test_results_path": str((workspace_root / ".ai" / "codegraph" / "test-results.json")),
            "handoff_path": str(runtime_paths(workspace_root)["handoff_latest"]),
        }
    if command_name == "demo":
        return {"workspace_root": str(payload) if isinstance(payload, pathlib.Path) else None}
    if command_name == "export-skill" and isinstance(payload, dict):
        return {"out_dir": payload.get("out_dir")}
    if command_name == "status":
        return {"handoff_path": str(runtime_paths(workspace_root)["handoff_latest"])}
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified Code Impact Guardian entry point")
    parser.add_argument("--debug", action="store_true", help="Show traceback on failures")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Bootstrap config, schema, and artifact directories")
    init_parser.add_argument("--workspace-root", default=".")
    init_parser.add_argument("--profile", default=None)
    init_parser.add_argument("--project-root", default=None)
    init_parser.add_argument("--with", dest="with_adapters", action="append", default=[])
    init_parser.add_argument("--write-agents-md", action="store_true")
    init_parser.add_argument("--write-gitignore", action="store_true")

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
    demo_parser.add_argument("--fixture", choices=["python_minimal", "tsjs_minimal", "generic_minimal", "tsjs_node_cli", "tsx_react_vite", "sql_pg_minimal", "tsjs_pg_compound"], default="python_minimal")
    demo_parser.add_argument("--workspace", default=None)

    export_parser = subparsers.add_parser("export-skill", help="Export a minimal distribution package")
    export_parser.add_argument("--workspace-root", default=".")
    export_parser.add_argument("--out", required=True)

    status_parser = subparsers.add_parser("status", help="Show current config, recent runs, and handoff state")
    status_parser.add_argument("--workspace-root", default=".")
    status_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    args = parser.parse_args()
    workspace_root = pathlib.Path(getattr(args, "workspace_root", ".")).resolve()
    ensure_runtime_dirs(workspace_root)
    config_path = pathlib.Path(getattr(args, "config", ".code-impact-guardian/config.json"))
    if not config_path.is_absolute():
        config_path = (workspace_root / config_path).resolve()

    task_id = getattr(args, "task_id", None)
    seed = getattr(args, "seed", None)
    context = {"project_root": None, "profile": None, "primary_adapter": None, "supplemental_adapters": []}

    try:
        if args.command == "demo":
            payload = run_demo(args.fixture, args.workspace)
            workspace_root = payload if isinstance(payload, pathlib.Path) else workspace_root
            demo_config_path = config_path_for(workspace_root)
            context = command_context(workspace_root, demo_config_path)
            event = event_payload(
                command="demo",
                workspace_root=workspace_root,
                project_root=context["project_root"],
                profile=context["profile"],
                primary_adapter=context["primary_adapter"],
                supplemental_adapters=context["supplemental_adapters"],
                task_id=None,
                seed=None,
                status="success",
                output_paths=normalize_output_paths(workspace_root, output_paths_for_command("demo", workspace_root, payload, demo_config_path)),
                warning_count=0,
                error_code=None,
                retryable=False,
                suggested_next_step=success_next_step("demo"),
            )
            write_event(workspace_root, event)
            print(workspace_root)
            return 0

        if args.command == "export-skill":
            payload = export_skill(workspace_root=workspace_root, out_dir=pathlib.Path(args.out).resolve())
            event = event_payload(
                command="export-skill",
                workspace_root=workspace_root,
                project_root=None,
                profile=None,
                primary_adapter=None,
                supplemental_adapters=[],
                task_id=None,
                seed=None,
                status="success",
                output_paths=normalize_output_paths(workspace_root, output_paths_for_command("export-skill", workspace_root, payload, None)),
                warning_count=0,
                error_code=None,
                retryable=False,
                suggested_next_step=success_next_step("export-skill"),
            )
            write_event(workspace_root, event)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        if args.command == "init":
            payload = init_workspace(
                workspace_root,
                profile=args.profile,
                project_root=args.project_root,
                with_adapters=args.with_adapters,
                write_agents_md=args.write_agents_md,
                write_gitignore=args.write_gitignore,
            )
            current_config_path = config_path_for(workspace_root)
            context = command_context(workspace_root, current_config_path)
            event = event_payload(
                command="init",
                workspace_root=workspace_root,
                project_root=context["project_root"],
                profile=context["profile"],
                primary_adapter=context["primary_adapter"],
                supplemental_adapters=context["supplemental_adapters"],
                task_id=None,
                seed=None,
                status="success",
                output_paths=normalize_output_paths(workspace_root, output_paths_for_command("init", workspace_root, payload, current_config_path)),
                warning_count=0,
                error_code=None,
                retryable=False,
                suggested_next_step=success_next_step("init"),
            )
            write_event(workspace_root, event)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        ensure_config_exists(config_path)
        context = command_context(workspace_root, config_path)

        if args.command == "doctor":
            payload = doctor_payload(workspace_root, config_path)
            warning_count = sum(1 for item in payload["statuses"] if item["level"] == "WARN")
            if payload["overall"] == "FAIL":
                error_code = (
                    "SUPPLEMENTAL_ADAPTER_MISSING"
                    if any("sql_postgres enabled but no configured SQL source/test paths were found" in item["message"] for item in payload["statuses"])
                    else "DOCTOR_FAILED"
                )
                raise CIGUserError(
                    error_code,
                    "Doctor checks reported a blocking failure.",
                    retryable=True,
                    suggested_next_step="Read TROUBLESHOOTING.md and fix the failing doctor checks before retrying.",
                )
            event = event_payload(
                command="doctor",
                workspace_root=workspace_root,
                project_root=context["project_root"],
                profile=context["profile"],
                primary_adapter=context["primary_adapter"],
                supplemental_adapters=context["supplemental_adapters"],
                task_id=None,
                seed=None,
                status="success",
                output_paths={},
                warning_count=warning_count,
                error_code=None,
                retryable=False,
                suggested_next_step=success_next_step("doctor"),
            )
            write_event(workspace_root, event)
            print_doctor(payload)
            return 0

        if args.command == "detect":
            payload = detect_payload(workspace_root, config_path)
        elif args.command == "build":
            payload = build_graph.build_graph(workspace_root=workspace_root, config_path=config_path)
        elif args.command == "seeds":
            payload = list_seeds.list_seeds(workspace_root=workspace_root, config_path=config_path)
        elif args.command == "report":
            payload = generate_report.generate_report(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=args.task_id,
                seed=args.seed,
                max_depth=args.max_depth,
            )
        elif args.command == "after-edit":
            payload = after_edit_update.after_edit_update(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=args.task_id,
                seed=args.seed,
                changed_files=args.changed_file,
            )
            if payload["tests"]["status"] != "passed":
                handoff_path = write_handoff(
                    workspace_root,
                    task_id=args.task_id,
                    command="after-edit",
                    status="failed",
                    failure_point="TEST_COMMAND_FAILED",
                    suggested_next_step="Inspect test-results.json and the output log, fix the test command or code, then rerun after-edit.",
                    seed=args.seed,
                    report_path=payload["report"]["report_path"],
                    test_results_path=str(workspace_root / ".ai" / "codegraph" / "test-results.json"),
                )
                raise CIGUserError(
                    "TEST_COMMAND_FAILED",
                    "after-edit refreshed the graph and report, but the test command failed.",
                    retryable=True,
                    suggested_next_step="Inspect handoff/latest.md and test-results.json, then rerun after-edit after fixing the failure.",
                    output_paths={
                        "report_path": payload["report"]["report_path"],
                        "test_results_path": str(workspace_root / ".ai" / "codegraph" / "test-results.json"),
                        "handoff_path": str(handoff_path),
                    },
                )
            write_handoff(
                workspace_root,
                task_id=args.task_id,
                command="after-edit",
                status="completed",
                failure_point="none",
                suggested_next_step="Review the updated report and test results, then continue with the next task.",
                seed=args.seed,
                report_path=payload["report"]["report_path"],
                test_results_path=str(workspace_root / ".ai" / "codegraph" / "test-results.json"),
            )
        elif args.command == "status":
            payload = status_payload(workspace_root, config_path)
        else:
            raise CIGUserError(
                "COMMAND_UNHANDLED",
                f"Unhandled command: {args.command}",
                retryable=False,
                suggested_next_step="Use one of the supported commands from cig.py --help.",
            )

        event = event_payload(
            command=args.command,
            workspace_root=workspace_root,
            project_root=context["project_root"],
            profile=context["profile"],
            primary_adapter=context["primary_adapter"],
            supplemental_adapters=context["supplemental_adapters"],
            task_id=task_id,
            seed=seed,
            status="success",
            output_paths=normalize_output_paths(workspace_root, output_paths_for_command(args.command, workspace_root, payload, config_path)),
            warning_count=0,
            error_code=None,
            retryable=False,
            suggested_next_step=success_next_step(args.command),
        )
        write_event(workspace_root, event)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        error_info = error_payload_from_exception(
            command=args.command,
            workspace_root=workspace_root,
            project_root=context["project_root"],
            profile=context["profile"],
            primary_adapter=context["primary_adapter"],
            supplemental_adapters=context["supplemental_adapters"],
            task_id=task_id,
            seed=seed,
            exc=exc,
            debug=args.debug,
        )
        write_error(workspace_root, error_info)
        write_event(workspace_root, error_info)
        write_handoff(
            workspace_root,
            task_id=task_id,
            command=args.command,
            status="failed",
            failure_point=error_info["error_code"],
            suggested_next_step=error_info["suggested_next_step"],
            seed=seed,
            report_path=error_info["output_paths"].get("report_path"),
            test_results_path=error_info["output_paths"].get("test_results_path"),
        )
        if args.debug:
            traceback.print_exc()
        else:
            print(f"ERROR [{error_info['error_code']}]: {error_info['message']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
