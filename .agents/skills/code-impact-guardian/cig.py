#!/usr/bin/env python3
import argparse
import json
import pathlib
import re
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
from consumer_install import ensure_agents_md as ensure_consumer_agents_md, ensure_consumer_docs, ensure_gitignore as ensure_consumer_gitignore, export_single_folder  # noqa: E402
from doc_sources import doc_source_doctor_status  # noqa: E402
from profiles import AUTO_PROFILE, PROFILE_PRESETS, apply_profile_preset, detect_project_profile, package_json_data, profile_coverage_adapter, profile_test_command  # noqa: E402
from recent_task import auto_task_id, latest_seed_candidates, read_last_task, utc_now as recent_task_utc_now, write_last_task  # noqa: E402
from runtime_support import CIGUserError, ensure_runtime_dirs, error_payload_from_exception, event_payload, latest_success_timestamp, normalize_output_paths, read_json, read_jsonl, recent_command_status, relative_path_string, runtime_paths, shell_quote_path, write_error, write_event, write_handoff, write_json  # noqa: E402
from context_inference import infer_context, stdin_patch_if_available  # noqa: E402
from seed_ranker import rank_seed_candidates  # noqa: E402


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
        "freshness_ttl_hours": 24,
        "exclude_dirs": [
            ".git",
            ".ai",
            "node_modules",
            "dist",
            "build",
            ".next",
            ".nuxt",
            ".turbo",
            ".cache",
            "coverage",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".playwright",
            "test-results",
        ],
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
    "verification_policy": {
        "default_budget": "B2",
        "budgets": {
            "B0": "no-op or docs-only",
            "B1": "health + analyze only",
            "B2": "targeted tests",
            "B3": "configured tests",
            "B4": "full tests + dependency/schema review",
        },
    },
}


DEFAULT_SCHEMA_TEXT = """PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repo_meta (
  meta_key TEXT PRIMARY KEY,
  meta_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
  node_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN (
    'file', 'function', 'test', 'rule',
    'endpoint', 'route', 'component', 'prop', 'event',
    'config_key', 'env_var', 'sql_table', 'ipc_channel',
    'obsidian_command', 'playwright_flow'
  )),
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
  edge_type TEXT NOT NULL CHECK(edge_type IN (
    'DEFINES', 'CALLS', 'IMPORTS', 'COVERS', 'GOVERNS',
    'READS_CONFIG', 'READS_ENV', 'EMITS_EVENT', 'HANDLES_EVENT',
    'QUERIES_TABLE', 'MUTATES_TABLE', 'ROUTES_TO', 'RENDERS_COMPONENT',
    'USES_PROP', 'REGISTER_COMMAND', 'IPC_SENDS', 'IPC_HANDLES'
  )),
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
  ('schema_version', '3'),
  ('graph_mode', 'direct-edges-only')
ON CONFLICT(meta_key) DO UPDATE SET meta_value = excluded.meta_value;
"""


def template_root() -> pathlib.Path:
    return SKILL_DIR.parents[2]


def template_asset(name: str) -> pathlib.Path:
    return SKILL_DIR / "assets" / "templates" / name


def reference_asset(name: str) -> pathlib.Path:
    return SKILL_DIR / "references" / name


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
    base_ignore = shutil.ignore_patterns(".git", ".ai", "__pycache__", "*.pyc", "dist", "*.zip")

    def ignore(current_dir: str, entries: list[str]) -> set[str]:
        ignored = set(base_ignore(current_dir, entries))
        if pathlib.Path(current_dir).name == ".code-impact-guardian":
            ignored.add("config.json")
        return {entry for entry in entries if entry in ignored}

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
    write_agents_md: bool = True,
    write_gitignore: bool = True,
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

    use_existing_config = config_path.exists() and project_root is None and profile in (None, AUTO_PROFILE) and not with_adapters
    config_payload = load_json(config_path) if use_existing_config else default_config_payload()
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
    consumer_docs = {}
    if write_agents_md:
        agents_md_path = ensure_consumer_agents_md(workspace_root)
    if write_gitignore:
        gitignore_path = ensure_consumer_gitignore(workspace_root)
    consumer_docs = ensure_consumer_docs(workspace_root)

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
        **consumer_docs,
    }


def set_fixture_config(workspace_root: pathlib.Path, fixture: str, persist: bool) -> pathlib.Path:
    config_path = config_path_for(workspace_root)
    payload = load_json(config_path)
    payload["project_root"] = f"examples/{fixture}"
    payload["primary_adapter"] = "auto"
    payload["language_adapter"] = "auto"
    if fixture == "generic_minimal":
        payload.setdefault("generic", {})
        payload["generic"]["test_command"] = [
            "python",
            "-c",
            "import pathlib; data = (pathlib.Path('src') / 'settings.conf').read_text(encoding='utf-8'); assert 'mode=active' in data",
        ]
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
    package_manager = detect_package_manager(project_root)
    test_command_candidates = detect_test_command_candidates(project_root, config, detected_adapter, detected_profile)
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
        "package_manager": package_manager,
        "test_command_candidates": test_command_candidates,
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


def detect_package_manager(project_root: pathlib.Path) -> str | None:
    markers = [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("bun.lock", "bun"),
        ("package-lock.json", "npm"),
    ]
    for marker, manager in markers:
        if (project_root / marker).exists():
            return manager
    if (project_root / "package.json").exists():
        return "npm"
    return None


def detect_test_command_candidates(project_root: pathlib.Path, config: dict, adapter_name: str, profile_name: str) -> list[list[str]]:
    if adapter_name == "python":
        if (project_root / "pytest.ini").exists():
            return [["pytest"]]
        pyproject = project_root / "pyproject.toml"
        if pyproject.exists() and "pytest" in pyproject.read_text(encoding="utf-8", errors="ignore").lower():
            return [["pytest"]]
        return [["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]]
    if adapter_name == "tsjs":
        preferred = profile_test_command(profile_name, project_root, config, "tsjs")
        candidates = [preferred]
        package_data = package_json_data(project_root)
        scripts = package_data.get("scripts", {})
        for script_name in ("test", "test:node-cli", "test:react-vite"):
            if script_name in scripts:
                candidates.append(["npm", "run", script_name])
        return candidates
    return []


def export_skill(*, workspace_root: pathlib.Path, out_dir: pathlib.Path, mode: str = "full") -> dict:
    resolved_mode = mode
    if mode == "full":
        resolved_mode = "consumer"
    if resolved_mode == "single-folder":
        return export_single_folder(SKILL_DIR, out_dir)
    if resolved_mode == "debug-bundle":
        if out_dir.exists():
            shutil.rmtree(out_dir)
        consumer_payload = export_skill(workspace_root=workspace_root, out_dir=out_dir, mode="consumer")
        debug_root = out_dir / "debug-bundle" / ".ai" / "codegraph"
        debug_root.mkdir(parents=True, exist_ok=True)
        runtime = workspace_root / ".ai" / "codegraph"
        for relative in (
            pathlib.Path("logs"),
            pathlib.Path("reports"),
            pathlib.Path("handoff"),
            pathlib.Path("last-task.json"),
            pathlib.Path("context-resolution.json"),
            pathlib.Path("build-decision.json"),
            pathlib.Path("seed-candidates.json"),
            pathlib.Path("next-action.json"),
        ):
            source = runtime / relative
            target = debug_root / relative
            if source.is_dir():
                shutil.copytree(
                    source,
                    target,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            elif source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        return {
            **consumer_payload,
            "mode": "debug-bundle",
            "exported_files": [*consumer_payload.get("exported_files", []), "debug-bundle/.ai/codegraph/"],
        }
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SKILL_DIR,
        out_dir / ".agents" / "skills" / "code-impact-guardian",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ai", ".git", "dist", "*.zip", "tests", "examples", "benchmark"),
    )
    package_config_dir = out_dir / ".code-impact-guardian"
    package_config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(schema_path_for(workspace_root), package_config_dir / "schema.sql")
    (package_config_dir / "config.template.json").write_text(
        json.dumps(default_config_template_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(template_asset("AGENTS.template.md"), out_dir / "AGENTS.template.md")
    shutil.copy2(template_asset("QUICKSTART.template.md"), out_dir / "QUICKSTART.md")
    shutil.copy2(template_asset("TROUBLESHOOTING.template.md"), out_dir / "TROUBLESHOOTING.md")
    if template_asset("CONSUMER_GUIDE.template.md").exists():
        shutil.copy2(template_asset("CONSUMER_GUIDE.template.md"), out_dir / "CONSUMER_GUIDE.md")
    return {
        "status": "exported",
        "mode": "consumer",
        "out_dir": str(out_dir),
        "exported_files": [
            "AGENTS.template.md",
            "QUICKSTART.md",
            "TROUBLESHOOTING.md",
            "CONSUMER_GUIDE.md",
            ".code-impact-guardian/config.template.json",
            ".code-impact-guardian/schema.sql",
            ".agents/skills/code-impact-guardian/",
        ],
    }


def command_available(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def doctor_payload(workspace_root: pathlib.Path, config_path: pathlib.Path, *, fix_safe: bool = False) -> dict:
    statuses: list[dict] = []
    overall = "PASS"
    safe_fixes: list[str] = []

    def add_status(level: str, message: str) -> None:
        nonlocal overall
        statuses.append({"level": level, "message": message})
        if level == "FAIL":
            overall = "FAIL"
        elif level == "WARN" and overall != "FAIL":
            overall = "WARN"

    if fix_safe:
        ensure_runtime_dirs(workspace_root)
        safe_fixes.append(relative_path_string(workspace_root, ensure_consumer_agents_md(workspace_root)))
        safe_fixes.append(relative_path_string(workspace_root, ensure_consumer_gitignore(workspace_root)))
        safe_fixes.extend(
            relative_path_string(workspace_root, value)
            for value in ensure_consumer_docs(workspace_root).values()
        )

    if config_path.exists():
        add_status("PASS", f"config {config_path.relative_to(workspace_root)}")
    else:
        add_status("FAIL", f"config missing at {config_path.relative_to(workspace_root)}")
        return {"overall": overall, "statuses": statuses, "safe_fixes": [value for value in safe_fixes if value]}

    schema_path = schema_path_for(workspace_root)
    if schema_path.exists():
        add_status("PASS", f"schema {schema_path.relative_to(workspace_root)}")
    else:
        add_status("FAIL", f"schema missing at {schema_path.relative_to(workspace_root)}")
        return {"overall": overall, "statuses": statuses, "safe_fixes": [value for value in safe_fixes if value]}

    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    if project_root.exists():
        add_status("PASS", f"project_root {project_root}")
    else:
        add_status("FAIL", f"project_root missing: {project_root}")
        return {"overall": overall, "statuses": statuses, "safe_fixes": [value for value in safe_fixes if value]}

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
        return {"overall": overall, "statuses": statuses, "safe_fixes": [value for value in safe_fixes if value]}

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
        if fix_safe and not config.get("python", {}).get("test_command"):
            config.setdefault("python", {})["test_command"] = ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
            write_json(config_path, config)
            safe_fixes.append(str(config_path.relative_to(workspace_root)))
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
        package_manager = detect_package_manager(project_root)
        if package_manager:
            add_status("PASS", f"package manager suggestion: {package_manager}")
        else:
            add_status("WARN", "package manager could not be inferred; npm is the default suggestion")
        if fix_safe and not config.get("tsjs", {}).get("test_command"):
            config.setdefault("tsjs", {})["test_command"] = profile_test_command(detected_profile, project_root, config, "tsjs")
            write_json(config_path, config)
            safe_fixes.append(str(config_path.relative_to(workspace_root)))
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

    return {"overall": overall, "statuses": statuses, "safe_fixes": [value for value in safe_fixes if value]}


def print_doctor(payload: dict) -> None:
    print(f"OVERALL {payload['overall']}")
    for status in payload["statuses"]:
        print(f"{status['level']} {status['message']}")
    safe_fixes = [item for item in payload.get("safe_fixes", []) if item]
    if safe_fixes:
        print("SAFE_FIXES " + ", ".join(safe_fixes))


def status_payload(workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    paths = runtime_paths(workspace_root)
    config_exists = config_path.exists()
    config = build_graph.load_config(config_path) if config_exists else {}
    project_root = str(build_graph.project_root_for(workspace_root, config)) if config_exists else None
    events = read_jsonl(paths["events"])
    last_error = read_json(paths["last_error"])
    last_task = read_last_task(workspace_root)
    last_error_timestamp = (last_error or {}).get("timestamp")
    last_success_index = max((index for index, item in enumerate(events) if item.get("status") == "success"), default=-1)
    last_error_index = max((index for index, item in enumerate(events) if item.get("status") == "failed"), default=-1)
    has_unhandled_error = bool(last_error_timestamp and last_error_index >= last_success_index)
    recent_success = next((item for item in reversed(events) if item.get("status") == "success"), None)
    recent_failure = next((item for item in reversed(events) if item.get("status") == "failed"), None)
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

    latest_brief = (((last_task or {}).get("report_brief")) or ((read_json(paths["next_action"]) or {}).get("brief")) or {})
    if has_unhandled_error and last_error:
        next_step = last_error.get("suggested_next_step")
    elif read_json(paths["next_action"]):
        next_step = (read_json(paths["next_action"]) or {}).get("suggested_next_step")
    elif (recent_success or {}).get("command") in {"after-edit", "finish"}:
        next_step = "Review handoff/latest.md, then start the next task with `cig.py analyze --changed-file <path>`."
    elif (recent_success or {}).get("command") in {"report", "analyze"}:
        next_step = "Edit the code, then run `cig.py finish --changed-file <path> --test-scope targeted`."
    elif (recent_success or {}).get("command") == "build":
        next_step = "Run `cig.py analyze --changed-file <path>` to generate the next report."
    elif config_exists:
        next_step = "Run `cig.py analyze --changed-file <path>` or `cig.py seeds` to choose a seed."
    else:
        next_step = "Run `cig.py setup --project-root .` to initialize the repo-local workflow files."

    return {
        "mode": "brief",
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
            "setup": recent_command_status(events, "setup"),
            "analyze": recent_command_status(events, "analyze"),
            "finish": recent_command_status(events, "finish"),
        },
        "recent_success_step": recent_success,
        "recent_failed_step": recent_failure,
        "last_error": last_error,
        "last_task": last_task,
        "latest_report_path": latest_report_path,
        "latest_test_results_path": latest_test_results_path,
        "available_seed_count": available_seed_count or 0,
        "has_unhandled_error": has_unhandled_error,
        "handoff_path": str(paths["handoff_latest"]) if paths["handoff_latest"].exists() else None,
        "seed": (last_task or {}).get("seed"),
        "fallback_used": bool((last_task or {}).get("fallback_used")),
        "build_mode": (last_task or {}).get("build_mode"),
        "build_decision": read_json(paths["build_decision"]),
        "context_resolution": read_json(paths["context_resolution"]),
        "next_action": read_json(paths["next_action"]),
        "brief": latest_brief,
        "next_step": next_step,
    }


def health_payload(workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    paths = runtime_paths(workspace_root)
    config_exists = config_path.exists()
    issues: list[str] = []
    fix_commands: list[str] = []
    graph_trust = "unknown"
    graph_freshness = "unknown"
    dependency_fingerprint_status = "unknown"
    last_task = read_last_task(workspace_root) or {}

    if not config_exists:
        issues.append("config_missing")
        quoted_workspace_root = shell_quote_path(workspace_root)
        fix_commands.append(f"python .agents/skills/code-impact-guardian/cig.py setup --workspace-root {quoted_workspace_root} --project-root .")
        issues.append("graph_stale")
        fix_commands.append(f"python .agents/skills/code-impact-guardian/cig.py build --workspace-root {quoted_workspace_root} --full-rebuild")
    else:
        config = build_graph.load_config(config_path)
        graph = build_graph.graph_paths(workspace_root, config)
        build_decision_payload = read_json(paths["build_decision"]) or {}
        graph_trust = build_decision_payload.get("graph_trust", build_decision_payload.get("trust_level", "unknown"))
        graph_freshness = build_decision_payload.get("graph_freshness", "unknown")
        dependency_fingerprint_status = build_decision_payload.get("dependency_fingerprint_status", "unknown")
        if not graph["db_path"].exists() or graph_freshness != "fresh":
            issues.append("graph_stale")
            quoted_workspace_root = shell_quote_path(workspace_root)
            fix_commands.append(f"python .agents/skills/code-impact-guardian/cig.py build --workspace-root {quoted_workspace_root} --full-rebuild")

    last_task_phase = last_task.get("command", "none") if last_task else "none"
    needs_finish = last_task_phase in {"analyze", "report"} and (last_task.get("status") == "success")
    ready = not issues and not needs_finish
    if needs_finish:
        issues.append("finish_pending")
        fix_commands.insert(0, f"python .agents/skills/code-impact-guardian/cig.py finish --workspace-root {shell_quote_path(workspace_root)} --test-scope targeted")
    next_command = fix_commands[0] if fix_commands else f"python .agents/skills/code-impact-guardian/cig.py analyze --workspace-root {shell_quote_path(workspace_root)} --changed-file <relative-path>"

    return {
        "ready": ready,
        "issues": issues,
        "fix_commands": fix_commands,
        "next_command": next_command,
        "graph_trust": graph_trust,
        "graph_freshness": graph_freshness,
        "dependency_fingerprint_status": dependency_fingerprint_status,
        "last_task_phase": last_task_phase,
        "needs_finish": needs_finish,
    }


def candidate_brief(item: dict) -> dict:
    return {
        "node_id": item.get("node_id"),
        "kind": item.get("kind"),
        "path": item.get("path"),
        "symbol": item.get("symbol"),
        "start_line": item.get("start_line"),
        "end_line": item.get("end_line"),
        "reason": item.get("reason"),
        "reason_details": item.get("reason_details", []),
    }


def write_machine_outputs(
    workspace_root: pathlib.Path,
    *,
    context_resolution: dict | None = None,
    seed_candidates: dict | None = None,
    next_action: dict | None = None,
) -> dict:
    paths = runtime_paths(workspace_root)
    written: dict[str, str] = {}
    if context_resolution is not None:
        write_json(paths["context_resolution"], context_resolution)
        written["context_resolution_path"] = str(paths["context_resolution"])
    if seed_candidates is not None:
        write_json(paths["seed_candidates"], seed_candidates)
        written["seed_candidates_path"] = str(paths["seed_candidates"])
    if next_action is not None:
        write_json(paths["next_action"], next_action)
        written["next_action_path"] = str(paths["next_action"])
    return written


def read_report_json_payload(report_payload: dict | None) -> dict:
    json_report_path = (report_payload or {}).get("json_report_path")
    if not json_report_path:
        return {}
    path = pathlib.Path(json_report_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def unique_paths(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def seed_path(seed_id: str) -> str | None:
    parts = seed_id.split(":", 2)
    if len(parts) < 2:
        return None
    return parts[1]


def verification_policy_payload(config: dict) -> dict:
    policy = config.get("verification_policy") or DEFAULT_CONFIG["verification_policy"]
    return {"verification_policy": json.loads(json.dumps(policy))}


def ensure_verification_policy_file(workspace_root: pathlib.Path, config_path: pathlib.Path) -> pathlib.Path:
    config = build_graph.load_config(config_path)
    paths = runtime_paths(workspace_root)
    write_json(paths["verification_policy"], verification_policy_payload(config))
    return paths["verification_policy"]


def docs_or_comment_only_changed_files(changed_files: list[str]) -> bool:
    if not changed_files:
        return False
    normalized = [item.replace("\\", "/") for item in changed_files]
    if not all(item.endswith((".md", ".txt", ".rst")) for item in normalized):
        return False
    return not any("/rules/" in item or item.startswith("docs/rules/") for item in normalized)


def dependency_or_schema_change(changed_files: list[str]) -> bool:
    risky_suffixes = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb", "tsconfig.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "poetry.lock", "pipfile", "pipfile.lock"}
    normalized = [item.replace("\\", "/").lower() for item in changed_files]
    for item in normalized:
        name = pathlib.PurePosixPath(item).name
        if name in risky_suffixes:
            return True
        if any(part in {"migrations", "migration", "schema", "schemas"} for part in pathlib.PurePosixPath(item).parts):
            return True
        if item.endswith((".sql", ".env", ".env.local")):
            return True
    return False


def previous_targeted_miss_exists(workspace_root: pathlib.Path, changed_files: list[str]) -> bool:
    if not changed_files:
        return False
    changed_file_set = set(changed_files)
    for row in read_jsonl(runtime_paths(workspace_root)["calibration"]):
        if not set(row.get("changed_files", [])) & changed_file_set:
            continue
        selection_quality = row.get("selection_quality") or {}
        if selection_quality.get("shadow_run") and not selection_quality.get("safe", True):
            return True
    return False


def recommended_scope_for_budget(budget: str) -> str:
    return {
        "B0": "targeted",
        "B1": "targeted",
        "B2": "targeted",
        "B3": "configured",
        "B4": "full",
    }.get(budget, "configured")


def decide_verification_budget(
    *,
    workspace_root: pathlib.Path,
    changed_files: list[str],
    changed_symbols: list[str],
    dependency_fingerprint_status: str,
    graph_trust: str,
    parser_confidence: float | None,
    parser_warning: str | None,
    direct_tests_count: int,
    affected_node_count: int,
    exported_symbol_touched: bool,
    risk_sensitive_change: bool,
    report_completeness: dict | None,
    must_read_first: list[str],
) -> dict:
    del changed_symbols
    reason_codes: list[str] = []
    budget = "B2"
    if docs_or_comment_only_changed_files(changed_files):
        budget = "B0"
        reason_codes.append("docs_only")
    elif not changed_files:
        budget = "B1"
        reason_codes.append("analyze_only")
    if dependency_fingerprint_status == "changed":
        budget = "B4"
        reason_codes.append("dependency_changed")
    elif dependency_fingerprint_status == "unknown" and budget not in {"B4"}:
        budget = "B3"
        reason_codes.append("dependency_unknown")
    if risk_sensitive_change and budget != "B4":
        budget = "B4"
        reason_codes.append("schema_or_config_change")
    if graph_trust == "low" and budget in {"B0", "B1", "B2"}:
        budget = "B3"
        reason_codes.append("graph_trust_low")
    if parser_warning and budget in {"B0", "B1", "B2"}:
        budget = "B3"
        reason_codes.append("parser_warning")
    if parser_confidence is not None and parser_confidence < 0.75 and budget in {"B0", "B1", "B2"}:
        budget = "B3"
        reason_codes.append("parser_confidence_low")
    if previous_targeted_miss_exists(workspace_root, changed_files) and budget in {"B0", "B1", "B2"}:
        budget = "B3"
        reason_codes.append("targeted_miss_history")
    if not direct_tests_count and budget in {"B0", "B1", "B2"}:
        budget = "B3"
        reason_codes.append("no_direct_tests")
    if exported_symbol_touched and budget in {"B0", "B1", "B2"}:
        budget = "B3"
        reason_codes.append("public_api_touched")
    if affected_node_count >= 6 and budget != "B4":
        budget = "B4"
        reason_codes.append("large_blast_radius")
    if direct_tests_count and len(changed_files) == 1 and budget == "B2":
        reason_codes.append("direct_tests_available")
    if (report_completeness or {}).get("level") == "low" and budget in {"B0", "B1", "B2"}:
        budget = "B3"
        reason_codes.append("context_incomplete")
    if not reason_codes:
        reason_codes.append("default_budget_path")
    return {
        "budget": budget,
        "reason_codes": reason_codes,
        "recommended_test_scope": recommended_scope_for_budget(budget),
        "must_read_first": must_read_first,
        "blocking": False,
    }


CIG_MANAGED_BLOCK_START = "<!-- CIG:START -->"
CIG_MANAGED_BLOCK_END = "<!-- CIG:END -->"


def render_integration_block() -> str:
    return "\n".join(
        [
            CIG_MANAGED_BLOCK_START,
            "## Code Impact Guardian Runtime Contract",
            "",
            "Adaptive Verification Orchestrator is active in this repo.",
            "",
            "- Start with `python .agents/skills/code-impact-guardian/cig.py health`.",
            "- Run `python .agents/skills/code-impact-guardian/cig.py analyze` before edits.",
            "- Read `.ai/codegraph/next-action.json` and follow its verification budget.",
            "- Use `finish --test-scope targeted` for low-risk edits, and add `--shadow-full` when you want calibration evidence.",
            "- Prefer this repo-local contract over runtime-private hook/config files.",
            CIG_MANAGED_BLOCK_END,
            "",
        ]
    )


def upsert_cig_managed_block(agents_path: pathlib.Path) -> pathlib.Path:
    block = render_integration_block()
    if agents_path.exists():
        content = agents_path.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"{re.escape(CIG_MANAGED_BLOCK_START)}[\s\S]*?{re.escape(CIG_MANAGED_BLOCK_END)}\n?",
            re.MULTILINE,
        )
        if pattern.search(content):
            updated = pattern.sub(block, content, count=1)
        else:
            updated = content.rstrip() + "\n\n" + block
    else:
        updated = "# Workspace Rules\n\n" + block
    agents_path.write_text(updated, encoding="utf-8")
    return agents_path


def runtime_template_content(kind: str) -> str:
    if kind == "SESSION_START":
        return "# SESSION_START\n\n1. Run `cig.py health`.\n2. Restore pending changes, handoff, and next-action.\n3. Surface the current recommended commands.\n"
    if kind == "BEFORE_EDIT":
        return "# BEFORE_EDIT\n\n1. Read `.ai/codegraph/next-action.json`.\n2. If trust is low or risk is high, run `cig.py analyze` again.\n3. Do not start with a full suite by default.\n"
    if kind == "AFTER_EDIT":
        return "# AFTER_EDIT\n\n1. Record changed files in `.ai/codegraph/pending-changes.jsonl`.\n2. Run formatter if needed.\n3. Prefer budget-driven verification before handoff.\n"
    return "# BEFORE_STOP\n\n1. If pending changes exist, run `cig.py analyze` or `cig.py finish`.\n2. Surface `next-action.json` recommended commands.\n3. Leave a clear handoff when verification is incomplete.\n"


def install_integration_pack(*, workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    ensure_runtime_dirs(workspace_root)
    ensure_verification_policy_file(workspace_root, config_path)
    paths = runtime_paths(workspace_root)
    agents_path = upsert_cig_managed_block(workspace_root / "AGENTS.md")
    for key, kind in (
        ("runtime_session_start", "SESSION_START"),
        ("runtime_before_edit", "BEFORE_EDIT"),
        ("runtime_after_edit", "AFTER_EDIT"),
        ("runtime_before_stop", "BEFORE_STOP"),
    ):
        paths[key].write_text(runtime_template_content(kind), encoding="utf-8")
    if not paths["pending_changes"].exists():
        paths["pending_changes"].write_text("", encoding="utf-8")
    return {
        "agents_path": str(agents_path),
        "runtime_files": {
            "session_start": str(paths["runtime_session_start"]),
            "before_edit": str(paths["runtime_before_edit"]),
            "after_edit": str(paths["runtime_after_edit"]),
            "before_stop": str(paths["runtime_before_stop"]),
            "pending_changes": str(paths["pending_changes"]),
            "verification_policy": str(paths["verification_policy"]),
        },
    }


def next_action_payload(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    command_name: str,
    task_id: str | None,
    seed: str | None,
    report_payload: dict | None,
    build_payload: dict | None,
    seed_selection: dict | None,
    tests_payload: dict | None,
    fallback_used: bool,
) -> dict:
    build_decision = (build_payload or {}).get("build_decision", {})
    report_brief = (report_payload or {}).get("brief") or {}
    report_json = read_report_json_payload(report_payload)
    direct_payload = (report_payload or {}).get("direct") or (report_json.get("direct") or {})
    definition = (report_payload or {}).get("definition") or (report_json.get("definition") or {})
    changed_files = list((report_payload or {}).get("changed_files") or report_json.get("changed_files") or [])
    next_tests = report_brief.get("next_tests", [])
    test_signal = report_brief.get("test_signal", {})
    report_completeness = report_brief.get("report_completeness", {})
    trust = report_brief.get("trust") or (report_payload or {}).get("trust") or build_decision.get("trust") or {}
    recommend_payload = (
        after_edit_update.recommend_tests_for_task(
            workspace_root=workspace_root,
            config_path=config_path,
            task_id=task_id,
        )
        if task_id
        else {}
    )
    direct_tests = list(direct_payload.get("tests") or [])
    dependency_status = trust.get("dependency") or build_decision.get("dependency_fingerprint_status", "unknown")
    graph_trust = trust.get("graph") or build_decision.get("graph_trust", build_decision.get("trust_level", "unknown"))
    direct_summary = report_brief.get("direct_impact_summary", {})
    mapping_status = recommend_payload.get("mapping_status", "unavailable")
    tests_status = (tests_payload or {}).get("status")
    definition_attrs = definition.get("attrs", {})
    parser_confidence = definition_attrs.get("parser_confidence")
    parser_warning = definition_attrs.get("parser_warning")
    suggestion = success_next_step(command_name)
    recommended_action = "edit_code"
    if tests_status == "failed":
        recommended_action = "inspect_failed_tests"
        suggestion = "Inspect test-results.json and the failing test output, then rerun the most relevant tests before trusting the edit."
    elif build_decision.get("verification_status") == "mismatched":
        recommended_action = "run_full_rebuild"
        suggestion = "Run `cig.py build --full-rebuild` before relying on the current graph."
    elif fallback_used:
        recommended_action = "inspect_report"
        suggestion = "Review the brief report carefully because generic fallback reduced symbol-level confidence."
    elif tests_payload and not test_signal.get("affected_tests_found"):
        recommended_action = "continue_with_warning"
        if tests_status == "passed":
            suggestion = "Tests passed, but no directly affected tests were identified. Continue only with a warning mindset."
        elif tests_status == "skipped":
            suggestion = "Tests were skipped, and no directly affected tests were identified. Continue only with a warning mindset."
        else:
            suggestion = "No directly affected tests were identified. Continue only with a warning mindset."
    elif report_completeness.get("level") == "low":
        recommended_action = "inspect_report"
        suggestion = "The report is still incomplete, so confirm the seed or narrow the context before editing."

    must_read_first = unique_paths(
        [
            definition.get("path"),
            *changed_files,
            *[seed_path(item) for item in direct_tests[:3]],
        ]
    )
    budget_decision = decide_verification_budget(
        workspace_root=workspace_root,
        changed_files=changed_files,
        changed_symbols=[definition.get("symbol")] if definition.get("symbol") else [],
        dependency_fingerprint_status=dependency_status,
        graph_trust=graph_trust,
        parser_confidence=parser_confidence if isinstance(parser_confidence, (int, float)) else None,
        parser_warning=parser_warning,
        direct_tests_count=len(direct_tests),
        affected_node_count=sum(int(direct_summary.get(key, 0) or 0) for key in ("callers", "callees", "tests", "rules")),
        exported_symbol_touched=bool(definition_attrs.get("exported")),
        risk_sensitive_change=dependency_or_schema_change(changed_files),
        report_completeness=report_completeness,
        must_read_first=must_read_first,
    )
    recommended_test_scope = budget_decision["recommended_test_scope"]
    if recommended_test_scope == "targeted" and not direct_tests:
        recommended_test_scope = "configured"
    if recommended_test_scope == "targeted" and mapping_status == "unavailable":
        recommended_test_scope = "configured"

    risk_level = "low"
    if budget_decision["budget"] == "B4":
        risk_level = "high"
    elif tests_status == "failed":
        risk_level = "high"
    elif budget_decision["budget"] == "B3" or dependency_status == "unknown" or report_completeness.get("level") == "low" or graph_trust == "low" or tests_status == "skipped":
        risk_level = "medium"
    elif direct_summary.get("callers") or direct_summary.get("rules"):
        risk_level = "medium"
    can_edit_now = bool(seed)

    recommended_commands: list[str] = []
    if command_name == "analyze":
        recommended_commands.append(
            f"python .agents/skills/code-impact-guardian/cig.py finish --workspace-root . --test-scope {recommended_test_scope}"
        )
        if recommended_test_scope == "targeted":
            recommended_commands.append(
                "python .agents/skills/code-impact-guardian/cig.py finish --workspace-root . --test-scope configured"
            )
        elif recommended_test_scope == "configured" and dependency_status == "changed":
            recommended_commands.append(
                "python .agents/skills/code-impact-guardian/cig.py finish --workspace-root . --test-scope full"
            )

    if direct_tests and recommended_test_scope == "targeted":
        user_message = (
            f"This change mainly touches {', '.join(must_read_first[:2]) or seed}. "
            f"I found {len(direct_tests)} directly related test seed(s), so make the edit and run targeted tests first. "
            "If direct mapping is incomplete, fall back to the configured test command."
        )
    elif budget_decision["budget"] == "B4":
        user_message = (
            f"This change includes dependency-level risk around {', '.join(changed_files[:2]) or seed}. "
            "Do the smallest safe edit possible, then run at least the configured suite and prefer a full suite before calling it ready."
        )
    elif not direct_tests:
        user_message = (
            f"This change is centered on {', '.join(must_read_first[:2]) or seed}, but no direct tests were identified. "
            "Edit carefully and treat test coverage as unknown until a broader configured or full run completes."
        )
    else:
        user_message = (
            f"This change centers on {', '.join(must_read_first[:2]) or seed}. "
            f"Use {recommended_test_scope} verification next and read the linked files before claiming confidence."
        )

    agent_instruction = (
        "Do not claim the change is safe just because tests pass. "
        "Treat passing tests as evidence, not proof. "
        "Read the key files first, run the recommended scope, and if targeted mapping fails fall back to configured tests. "
        "If dependency state is changed or unknown, do not make a high-confidence safety claim without broader verification."
    )
    return {
        "command": command_name,
        "task_id": task_id,
        "selected_seed": seed,
        "seed_reason": (seed_selection or {}).get("reason"),
        "candidate_seeds": (seed_selection or {}).get("top_candidates", [])[:3],
        "seed_confidence": (seed_selection or {}).get("seed_confidence", (seed_selection or {}).get("confidence")),
        "recent_task_influenced": bool((seed_selection or {}).get("recent_task_influenced")),
        "recommended_action": recommended_action,
        "recommended_tests": next_tests[:3],
        "verification_budget": budget_decision["budget"],
        "budget_reason_codes": budget_decision["reason_codes"],
        "recommended_test_scope": recommended_test_scope,
        "recommended_test_commands": list(recommend_payload.get("recommended_tests") or []),
        "recommended_commands": recommended_commands,
        "risk_level": risk_level,
        "can_edit_now": can_edit_now,
        "must_read_first": must_read_first,
        "build_trust": {
            "build_mode": build_decision.get("execution_mode") or build_decision.get("build_mode"),
            "graph_trust": build_decision.get("graph_trust", build_decision.get("trust_level")),
            "reason_codes": build_decision.get("reason_codes", []),
            "verification_status": build_decision.get("verification_status"),
            "graph_freshness": build_decision.get("graph_freshness"),
            "dependency_fingerprint_status": build_decision.get("dependency_fingerprint_status"),
        },
        "trust": trust or build_decision.get("trust") or {},
        "report_completeness": report_completeness,
        "test_signal": test_signal,
        "user_message": user_message,
        "agent_instruction": agent_instruction,
        "user_summary": report_brief.get("user_summary"),
        "brief": report_brief,
        "report_path": (report_payload or {}).get("report_path"),
        "json_report_path": (report_payload or {}).get("json_report_path"),
        "suggested_next_step": suggestion,
    }


def resolve_seed_selection(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    explicit_seed: str | None,
    changed_files: list[str],
    changed_lines: list[str],
    allow_fallback: bool,
) -> tuple[str, dict]:
    if explicit_seed:
        return explicit_seed, {
            "mode": "explicit",
            "seed_confidence": 1.0,
            "confidence": 1.0,
            "reason": "explicit seed provided",
            "top_candidates": [{"node_id": explicit_seed, "confidence": 1.0, "seed_confidence": 1.0, "reason": "explicit seed provided", "reason_details": ["explicit seed provided"]}],
            "fallback_used": False,
            "recent_task_influenced": False,
        }

    ranked = rank_seed_candidates(
        workspace_root=workspace_root,
        config_path=config_path,
        changed_files=changed_files,
        changed_lines=changed_lines,
    )
    top_candidates = ranked.get("top_candidates", [])
    if ranked.get("selected_seed"):
        selected = ranked["selected_seed"]
        selected_candidate = next((item for item in top_candidates if item["node_id"] == selected), None)
        fallback_used = bool(selected_candidate and selected_candidate.get("kind") == "file")
        mode = "auto-ranked-file" if fallback_used else "auto-ranked"
        if len(top_candidates) == 1 and not changed_lines and not fallback_used:
            mode = "auto-single"
        return selected, {
            "mode": mode,
            "seed_confidence": ranked.get("confidence", 0.0),
            "confidence": ranked.get("confidence", 0.0),
            "reason": ranked.get("reason", "highest ranked candidate"),
            "top_candidates": top_candidates,
            "fallback_used": fallback_used,
            "recent_task_influenced": ranked.get("recent_task_influenced", False),
        }

    candidates = latest_seed_candidates(workspace_root, config_path)
    if not top_candidates and not candidates:
        raise CIGUserError(
            "SEED_NOT_FOUND",
            "No seed candidates were found for the current graph.",
            retryable=True,
            suggested_next_step="Run `cig.py build` first, then rerun `cig.py seeds` or `cig.py analyze --changed-file <path>`.",
        )
    if not top_candidates and len(candidates) == 1:
        return candidates[0]["node_id"], {
            "mode": "auto-single",
            "seed_confidence": 0.78,
            "confidence": 0.78,
            "reason": "single candidate available in current graph",
            "top_candidates": [candidate_brief(candidates[0])],
            "fallback_used": candidates[0].get("kind") == "file",
            "recent_task_influenced": False,
        }
    if allow_fallback:
        file_candidates = [item for item in (top_candidates or candidates[:3]) if item.get("kind") == "file"]
        if len(file_candidates) == 1:
            selected = file_candidates[0]
            return selected["node_id"], {
                "mode": "auto-fallback-file",
                "seed_confidence": selected.get("confidence", 0.65),
                "confidence": selected.get("confidence", 0.65),
                "reason": selected.get("reason", "generic fallback file candidate"),
                "top_candidates": top_candidates or [candidate_brief(selected)],
                "fallback_used": True,
                "recent_task_influenced": any("recent task" in detail for detail in selected.get("reason_details", [])),
            }
    shortlist = top_candidates or [candidate_brief(item) for item in candidates[:3]]
    suggestions = ", ".join(item["node_id"] for item in shortlist)
    raise CIGUserError(
        "SEED_SELECTION_REQUIRED",
        "Multiple seed candidates matched the current files.",
        retryable=True,
        suggested_next_step=f"Run the command again with --seed using one of: {suggestions}",
    )


def persist_last_task(
    workspace_root: pathlib.Path,
    *,
    command_name: str,
    task_id: str,
    seed: str,
    changed_files: list[str],
    config_path: pathlib.Path,
    context: dict,
    report_path: str | None = None,
    status: str = "success",
    seed_selection: dict | None = None,
    build_mode: str | None = None,
    fallback_used: bool = False,
    context_resolution: dict | None = None,
    trust_level: str | None = None,
    build_decision: dict | None = None,
    report_brief: dict | None = None,
    user_summary: str | None = None,
    graph_trust: str | None = None,
    report_completeness: dict | None = None,
    test_signal: dict | None = None,
) -> str:
    path = write_last_task(
        workspace_root,
        {
            "timestamp": recent_task_utc_now(),
            "command": command_name,
            "task_id": task_id,
            "seed": seed,
            "changed_files": changed_files,
            "config_path": str(config_path),
            "project_root": context.get("project_root"),
            "profile": context.get("profile"),
            "primary_adapter": context.get("primary_adapter"),
            "supplemental_adapters": context.get("supplemental_adapters", []),
            "report_path": report_path,
            "status": status,
            "seed_selection": seed_selection or {},
            "build_mode": build_mode,
            "fallback_used": fallback_used,
            "context_resolution": context_resolution or {},
            "trust_level": trust_level,
            "graph_trust": graph_trust or trust_level,
            "build_decision": build_decision or {},
            "report_brief": report_brief or {},
            "user_summary": user_summary,
            "report_completeness": report_completeness or {},
            "test_signal": test_signal or {},
        },
    )
    return str(path)


def context_missing_recovery_commands(workspace_root: pathlib.Path) -> list[str]:
    quoted_workspace_root = shell_quote_path(workspace_root)
    return [
        f"python .agents/skills/code-impact-guardian/cig.py analyze --workspace-root {quoted_workspace_root} --allow-fallback",
        f"python .agents/skills/code-impact-guardian/cig.py analyze --workspace-root {quoted_workspace_root} --changed-file <relative-path>",
        f"python .agents/skills/code-impact-guardian/cig.py analyze --workspace-root {quoted_workspace_root} --patch-file <patch-file>",
        f"git -C {quoted_workspace_root} init",
    ]


def run_analyze_command(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    task_id: str | None,
    seed: str | None,
    changed_files: list[str],
    changed_lines: list[str],
    max_depth: int | None,
    allow_fallback: bool,
    report_mode: str,
    patch_file: pathlib.Path | None = None,
    stdin_patch: str | None = None,
) -> dict:
    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    context_resolution = infer_context(
        workspace_root=workspace_root,
        project_root=project_root,
        explicit_seed=seed,
        explicit_changed_files=changed_files,
        explicit_changed_lines=changed_lines,
        patch_file=patch_file,
        stdin_patch=stdin_patch,
    )
    effective_changed_files = list(context_resolution.get("effective_changed_files") or context_resolution.get("changed_files") or changed_files)
    effective_changed_lines = list(context_resolution.get("effective_changed_lines") or context_resolution.get("changed_lines") or changed_lines)
    raw_changed_files = list(context_resolution.get("changed_files") or changed_files)
    raw_changed_lines = list(context_resolution.get("changed_lines") or changed_lines)
    context_resolution["effective_changed_files"] = effective_changed_files
    context_resolution["effective_changed_lines"] = effective_changed_lines
    context_resolution["context_incomplete"] = context_resolution.get("context_status") != "resolved"

    detect = detect_payload(workspace_root, config_path)

    if context_resolution.get("context_status") == "missing" and not seed:
        if not allow_fallback:
            write_machine_outputs(
                workspace_root,
                context_resolution=context_resolution,
                seed_candidates={"task_id": task_id, "candidates": []},
            )
            raise CIGUserError(
                "CONTEXT_MISSING",
                "Could not infer a stable seed or changed-file context for analyze.",
                retryable=True,
                suggested_next_step="Pass --changed-file, pass --patch-file, initialize git with `git init`, or rerun with --allow-fallback to continue file-level only.",
                recovery_commands=context_missing_recovery_commands(workspace_root),
            )

        build_payload = build_graph.build_graph(
            workspace_root=workspace_root,
            config_path=config_path,
            changed_files=[],
        )
        seeds_payload = list_seeds.list_seeds(workspace_root=workspace_root, config_path=config_path)
        file_candidates = [candidate_brief(item) for item in seeds_payload.get("file_details", [])[:3]]
        write_machine_outputs(
            workspace_root,
            context_resolution=context_resolution,
            seed_candidates={"task_id": task_id, "candidates": file_candidates},
        )
        if len(seeds_payload.get("file_details", [])) != 1:
            raise CIGUserError(
                "CONTEXT_MISSING",
                "Could not infer a stable seed or changed-file context for analyze.",
                retryable=True,
                suggested_next_step="Pass --changed-file, pass --patch-file, initialize git with `git init`, or rerun with --seed to continue explicitly.",
                recovery_commands=context_missing_recovery_commands(workspace_root),
            )

        selected_file = seeds_payload["file_details"][0]
        selected_seed = selected_file["node_id"]
        seed_selection = {
            "mode": "auto-fallback-file",
            "seed_confidence": 0.45,
            "confidence": 0.45,
            "reason": "context missing, but a single file-level candidate exists in the current graph",
            "top_candidates": file_candidates,
            "fallback_used": True,
            "recent_task_influenced": False,
        }
        context_resolution.update(
            {
                "selected_seed": selected_seed,
                "candidate_seeds": file_candidates,
                "seed_confidence": 0.45,
                "reason": seed_selection["reason"],
                "fallback_used": True,
                "context_incomplete": True,
            }
        )
        resolved_task_id = task_id or auto_task_id(seed=selected_seed, changed_files=effective_changed_files, prefix="analyze")
        suggested_next = "The current report is incomplete, so narrow the seed or pass --changed-file before editing."
        report_payload = generate_report.generate_report(
            workspace_root=workspace_root,
            config_path=config_path,
            task_id=resolved_task_id,
            seed=selected_seed,
            max_depth=max_depth,
            mode=report_mode,
            changed_files=effective_changed_files,
            seed_selection=seed_selection,
            build_decision=build_payload.get("build_decision"),
            next_step=suggested_next,
            context_resolution=context_resolution,
        )
        context = command_context(workspace_root, config_path)
        next_action = next_action_payload(
            workspace_root=workspace_root,
            config_path=config_path,
            command_name="analyze",
            task_id=resolved_task_id,
            seed=selected_seed,
            report_payload=report_payload,
            build_payload=build_payload,
            seed_selection=seed_selection,
            tests_payload=None,
            fallback_used=True,
        )
        machine_outputs = write_machine_outputs(
            workspace_root,
            context_resolution=context_resolution,
            seed_candidates={"task_id": resolved_task_id, "candidates": file_candidates},
            next_action=next_action,
        )
        machine_outputs["verification_policy_path"] = str(ensure_verification_policy_file(workspace_root, config_path))
        last_task_path_str = persist_last_task(
            workspace_root,
            command_name="analyze",
            task_id=resolved_task_id,
            seed=selected_seed,
            changed_files=effective_changed_files,
            config_path=config_path,
            context=context,
            report_path=report_payload.get("report_path"),
            seed_selection=seed_selection,
            build_mode=build_payload.get("build_mode"),
            fallback_used=True,
            context_resolution=context_resolution,
            trust_level=(build_payload.get("build_decision") or {}).get("trust_level"),
            graph_trust=(build_payload.get("build_decision") or {}).get("graph_trust"),
            build_decision=build_payload.get("build_decision"),
            report_brief=report_payload.get("brief"),
            user_summary=report_payload.get("user_summary"),
            report_completeness=report_payload.get("report_completeness"),
            test_signal=report_payload.get("test_signal"),
        )
        return {
            "task_id": resolved_task_id,
            "seed": selected_seed,
            "changed_files": effective_changed_files,
            "changed_lines": effective_changed_lines,
            "seed_selection": seed_selection,
            "fallback_used": True,
            "context_resolution": context_resolution,
            "detect": detect,
            "build": build_payload,
            "report": report_payload,
            "brief": report_payload.get("brief"),
            "machine_outputs": machine_outputs,
            "next_action": next_action,
            "last_task_path": last_task_path_str,
        }

    build_payload = build_graph.build_graph(
        workspace_root=workspace_root,
        config_path=config_path,
        changed_files=raw_changed_files,
    )
    preview_candidates = []
    if not seed:
        preview_ranked = rank_seed_candidates(
            workspace_root=workspace_root,
            config_path=config_path,
            changed_files=effective_changed_files,
            changed_lines=effective_changed_lines,
        )
        preview_candidates = preview_ranked.get("top_candidates", [])[:3]
        context_resolution.update(
            {
                "candidate_seeds": preview_candidates,
                "seed_confidence": preview_ranked.get("confidence", context_resolution.get("seed_confidence", 0.0)),
                "reason": preview_ranked.get("reason", context_resolution.get("reason")),
            }
        )
        write_machine_outputs(
            workspace_root,
            context_resolution=context_resolution,
            seed_candidates={"task_id": task_id, "candidates": preview_candidates},
        )
    selected_seed, seed_selection = resolve_seed_selection(
        workspace_root=workspace_root,
        config_path=config_path,
        explicit_seed=seed or context_resolution.get("selected_seed"),
        changed_files=effective_changed_files,
        changed_lines=effective_changed_lines,
        allow_fallback=allow_fallback,
    )
    context_resolution.update(
        {
            "selected_seed": selected_seed,
            "candidate_seeds": seed_selection.get("top_candidates", [])[:3],
            "seed_confidence": seed_selection.get("seed_confidence", seed_selection.get("confidence", context_resolution.get("seed_confidence", 0.0))),
            "reason": seed_selection.get("reason", context_resolution.get("reason")),
            "fallback_used": seed_selection.get("fallback_used", False),
            "changed_files": raw_changed_files,
            "changed_lines": raw_changed_lines,
            "context_incomplete": context_resolution.get("context_status") != "resolved" or seed_selection.get("fallback_used", False),
        }
    )
    resolved_task_id = task_id or auto_task_id(seed=selected_seed, changed_files=effective_changed_files, prefix="analyze")
    suggested_next = (
        "The current report is incomplete, so confirm the seed or narrow the diff before editing."
        if context_resolution.get("context_incomplete")
        else "If this brief looks right, edit the code and then run `cig.py finish`."
    )
    report_payload = generate_report.generate_report(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=resolved_task_id,
        seed=selected_seed,
        max_depth=max_depth,
        mode=report_mode,
        changed_files=effective_changed_files,
        seed_selection=seed_selection,
        build_decision=build_payload.get("build_decision"),
        next_step=suggested_next,
        context_resolution=context_resolution,
    )
    context = command_context(workspace_root, config_path)
    next_action = next_action_payload(
        workspace_root=workspace_root,
        config_path=config_path,
        command_name="analyze",
        task_id=resolved_task_id,
        seed=selected_seed,
        report_payload=report_payload,
        build_payload=build_payload,
        seed_selection=seed_selection,
        tests_payload=None,
        fallback_used=seed_selection.get("fallback_used", False),
    )
    machine_outputs = write_machine_outputs(
        workspace_root,
        context_resolution=context_resolution,
        seed_candidates={"task_id": resolved_task_id, "candidates": seed_selection.get("top_candidates", [])[:3]},
        next_action=next_action,
    )
    machine_outputs["verification_policy_path"] = str(ensure_verification_policy_file(workspace_root, config_path))
    last_task_path_str = persist_last_task(
        workspace_root,
        command_name="analyze",
        task_id=resolved_task_id,
        seed=selected_seed,
        changed_files=effective_changed_files,
        config_path=config_path,
        context=context,
        report_path=report_payload.get("report_path"),
        seed_selection=seed_selection,
        build_mode=build_payload.get("build_mode"),
        fallback_used=seed_selection.get("fallback_used", False),
        context_resolution=context_resolution,
        trust_level=(build_payload.get("build_decision") or {}).get("trust_level"),
        graph_trust=(build_payload.get("build_decision") or {}).get("graph_trust"),
        build_decision=build_payload.get("build_decision"),
        report_brief=report_payload.get("brief"),
        user_summary=report_payload.get("user_summary"),
        report_completeness=report_payload.get("report_completeness"),
        test_signal=report_payload.get("test_signal"),
    )
    return {
        "task_id": resolved_task_id,
        "seed": selected_seed,
        "changed_files": effective_changed_files,
        "changed_lines": effective_changed_lines,
        "seed_selection": seed_selection,
        "fallback_used": seed_selection.get("fallback_used", False),
        "context_resolution": context_resolution,
        "detect": detect,
        "build": build_payload,
        "report": report_payload,
        "brief": report_payload.get("brief"),
        "machine_outputs": machine_outputs,
        "next_action": next_action,
        "last_task_path": last_task_path_str,
    }


def resolve_finish_context(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    task_id: str | None,
    seed: str | None,
    changed_files: list[str],
    allow_fallback: bool,
    patch_file: pathlib.Path | None = None,
    stdin_patch: str | None = None,
) -> tuple[str, str, list[str], dict, dict]:
    last_task = read_last_task(workspace_root) or {}
    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    context_resolution = infer_context(
        workspace_root=workspace_root,
        project_root=project_root,
        explicit_seed=seed,
        explicit_changed_files=changed_files,
        explicit_changed_lines=[],
        patch_file=patch_file,
        stdin_patch=stdin_patch,
    )
    resolved_task_id = task_id or last_task.get("task_id")
    resolved_seed = seed or context_resolution.get("selected_seed") or last_task.get("seed")
    resolved_changed_files = list(context_resolution.get("effective_changed_files") or context_resolution.get("changed_files") or changed_files or list(last_task.get("changed_files", [])))
    if not resolved_seed and resolved_changed_files:
        resolved_seed, seed_selection = resolve_seed_selection(
            workspace_root=workspace_root,
            config_path=config_path,
            explicit_seed=None,
            changed_files=resolved_changed_files,
            changed_lines=[],
            allow_fallback=allow_fallback,
        )
        context_resolution["candidate_seeds"] = seed_selection.get("top_candidates", [])[:3]
        context_resolution["seed_confidence"] = seed_selection.get("seed_confidence", seed_selection.get("confidence", 0.0))
        context_resolution["reason"] = seed_selection.get("reason")
        context_resolution["fallback_used"] = seed_selection.get("fallback_used", False)
    if not resolved_task_id:
        resolved_task_id = auto_task_id(seed=resolved_seed, changed_files=resolved_changed_files, prefix="finish")
    if not resolved_seed:
        raise CIGUserError(
            "TASK_CONTEXT_MISSING",
            "No recent analyze/report context is available for finish.",
            retryable=True,
            suggested_next_step="Run `cig.py analyze --changed-file <path>` first, or rerun finish with --seed and --task-id.",
        )
    context_resolution["selected_seed"] = resolved_seed
    context_resolution["changed_files"] = resolved_changed_files
    return resolved_task_id, resolved_seed, resolved_changed_files, last_task, context_resolution


def finalize_after_edit(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    task_id: str,
    seed: str,
    changed_files: list[str],
    command_name: str,
    report_mode: str,
    context_resolution: dict | None = None,
    test_scope: str = "configured",
    shadow_full: bool = False,
) -> dict:
    payload = after_edit_update.after_edit_update(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
        seed=seed,
        changed_files=changed_files,
        report_mode=report_mode,
        test_scope=test_scope,
        shadow_full=shadow_full,
        source=command_name,
    )
    context = command_context(workspace_root, config_path)
    next_action = next_action_payload(
        workspace_root=workspace_root,
        config_path=config_path,
        command_name=command_name,
        task_id=task_id,
        seed=seed,
        report_payload=payload.get("report"),
        build_payload=payload.get("graph"),
        seed_selection=(read_last_task(workspace_root) or {}).get("seed_selection"),
        tests_payload=payload.get("tests"),
        fallback_used=bool((context_resolution or {}).get("fallback_used")),
    )
    machine_outputs = write_machine_outputs(
        workspace_root,
        context_resolution=context_resolution,
        next_action=next_action,
    )
    machine_outputs["verification_policy_path"] = str(ensure_verification_policy_file(workspace_root, config_path))
    after_edit_update.backfill_test_history_budget(
        workspace_root=workspace_root,
        task_id=task_id,
        budget=next_action.get("verification_budget"),
    )
    payload.setdefault("tests", {})["verification_budget"] = next_action.get("verification_budget")
    payload.setdefault("tests", {})["budget_reason_codes"] = next_action.get("budget_reason_codes", [])
    if payload["tests"]["status"] == "failed":
        handoff_path = write_handoff(
            workspace_root,
            task_id=task_id,
            command=command_name,
            status="failed",
            failure_point="TEST_COMMAND_FAILED",
            suggested_next_step="Inspect test-results.json and the output log, fix the test command or code, then rerun finish/after-edit.",
            seed=seed,
            report_path=payload["report"]["report_path"],
            test_results_path=str(workspace_root / ".ai" / "codegraph" / "test-results.json"),
        )
        persist_last_task(
            workspace_root,
            command_name=command_name,
            task_id=task_id,
            seed=seed,
            changed_files=changed_files,
            config_path=config_path,
            context=context,
            report_path=payload["report"]["report_path"],
            status="failed",
            seed_selection=(read_last_task(workspace_root) or {}).get("seed_selection"),
            build_mode=payload.get("graph", {}).get("build_mode"),
            fallback_used=bool((read_last_task(workspace_root) or {}).get("fallback_used")),
            context_resolution=context_resolution,
            trust_level=(payload.get("graph", {}).get("build_decision") or {}).get("trust_level"),
            graph_trust=(payload.get("graph", {}).get("build_decision") or {}).get("graph_trust"),
            build_decision=payload.get("graph", {}).get("build_decision"),
            report_brief=payload.get("report", {}).get("brief"),
            user_summary=payload.get("report", {}).get("user_summary"),
            report_completeness=payload.get("report", {}).get("report_completeness"),
            test_signal=payload.get("report", {}).get("test_signal"),
        )
        raise CIGUserError(
            "TEST_COMMAND_FAILED",
            "Graph/report refresh succeeded, but the configured test command failed.",
            retryable=True,
            suggested_next_step="Inspect handoff/latest.md and test-results.json, fix the failing command or code, then rerun finish/after-edit.",
            output_paths={
                "report_path": payload["report"]["report_path"],
                "test_results_path": str(workspace_root / ".ai" / "codegraph" / "test-results.json"),
                "handoff_path": str(handoff_path),
            },
        )
    write_handoff(
        workspace_root,
        task_id=task_id,
        command=command_name,
        status="completed" if payload["tests"]["status"] == "passed" else "completed-with-warnings",
        failure_point="none" if payload["tests"]["status"] == "passed" else "TESTS_SKIPPED",
        suggested_next_step=(
            "Review the updated report and test results, then continue with the next task."
            if payload["tests"]["status"] == "passed"
            else "Tests were skipped. Review test-results.json, confirm that is acceptable for this repo, then continue or configure a real test command."
        ),
        seed=seed,
        report_path=payload["report"]["report_path"],
        test_results_path=str(workspace_root / ".ai" / "codegraph" / "test-results.json"),
    )
    last_task_path_str = persist_last_task(
        workspace_root,
        command_name=command_name,
        task_id=task_id,
        seed=seed,
        changed_files=changed_files,
        config_path=config_path,
        context=context,
        report_path=payload["report"]["report_path"],
        status="success",
        seed_selection=(read_last_task(workspace_root) or {}).get("seed_selection"),
        build_mode=payload.get("graph", {}).get("build_mode"),
        fallback_used=bool((read_last_task(workspace_root) or {}).get("fallback_used")),
        context_resolution=context_resolution,
        trust_level=(payload.get("graph", {}).get("build_decision") or {}).get("trust_level"),
        graph_trust=(payload.get("graph", {}).get("build_decision") or {}).get("graph_trust"),
        build_decision=payload.get("graph", {}).get("build_decision"),
        report_brief=payload.get("report", {}).get("brief"),
        user_summary=payload.get("report", {}).get("user_summary"),
        report_completeness=payload.get("report", {}).get("report_completeness"),
        test_signal=payload.get("report", {}).get("test_signal"),
    )
    payload["task_id"] = task_id
    payload["seed"] = seed
    payload["changed_files"] = changed_files
    payload["requested_test_scope"] = test_scope
    payload["last_task_path"] = last_task_path_str
    payload["context_resolution"] = context_resolution
    payload["next_action"] = next_action
    payload["machine_outputs"] = machine_outputs
    payload["brief"] = payload.get("report", {}).get("brief")
    return payload


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


def auto_setup_if_missing(workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict | None:
    if config_path.exists():
        return None
    return init_workspace(
        workspace_root,
        profile=AUTO_PROFILE,
        project_root=".",
        with_adapters=[],
        write_agents_md=True,
        write_gitignore=True,
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
        "setup": "Run `cig.py analyze` next. It will infer context from your working tree when possible.",
        "doctor": "Run `cig.py detect` next.",
        "detect": "Run `cig.py build` next.",
        "build": "Run `cig.py seeds` next.",
        "seeds": "Pick a seed and run `cig.py report`.",
        "report": "Read the report, edit the code, then run `cig.py after-edit`.",
        "after-edit": "Review the updated report, test results, and handoff note.",
        "analyze": "Edit the code, then run `cig.py finish --test-scope targeted`. It will reuse the latest task context when possible.",
        "recommend-tests": "Use the mapped commands for targeted verification, or fall back to the configured suite if mapping is unavailable.",
        "finish": "Review handoff/latest.md and start the next task when ready.",
        "demo": "Inspect the generated graph, report, logs, and handoff artifacts.",
        "export-skill": "Copy the exported package into a new repo and run `cig.py setup` there.",
        "status": "Inspect the latest error or continue from the suggested next command.",
    }
    return mapping.get(command_name, "Continue with the next workflow step.")


def requested_report_mode(args, default: str = "brief") -> str:
    if getattr(args, "full", False):
        return "full"
    if getattr(args, "brief", False):
        return "brief"
    return default


def output_paths_for_command(command_name: str, workspace_root: pathlib.Path, payload: dict | pathlib.Path | None, config_path: pathlib.Path | None) -> dict:
    if command_name == "init":
        return {
            "config_path": payload.get("config_path") if isinstance(payload, dict) else None,
            "schema_path": payload.get("schema_path") if isinstance(payload, dict) else None,
            "agents_md_path": payload.get("agents_md_path") if isinstance(payload, dict) else None,
            "gitignore_path": payload.get("gitignore_path") if isinstance(payload, dict) else None,
            "quickstart_path": payload.get("quickstart_path") if isinstance(payload, dict) else None,
            "troubleshooting_path": payload.get("troubleshooting_path") if isinstance(payload, dict) else None,
            "consumer_guide_path": payload.get("consumer_guide_path") if isinstance(payload, dict) else None,
        }
    if command_name == "setup" and isinstance(payload, dict):
        return {
            "config_path": payload.get("init", {}).get("config_path"),
            "schema_path": payload.get("init", {}).get("schema_path"),
            "agents_md_path": payload.get("init", {}).get("agents_md_path"),
            "gitignore_path": payload.get("init", {}).get("gitignore_path"),
        }
    if command_name == "doctor":
        return {}
    if command_name == "detect":
        return {}
    if command_name == "build":
        return {
            "db_path": str(build_graph.graph_paths(workspace_root, build_graph.load_config(config_path))["db_path"]) if config_path and config_path.exists() else None,
            "build_log_path": str(build_graph.graph_paths(workspace_root, build_graph.load_config(config_path))["build_log_path"]) if config_path and config_path.exists() else None,
            "build_decision_path": str(runtime_paths(workspace_root)["build_decision"]),
        }
    if command_name == "report" and isinstance(payload, dict):
        return {
            "report_path": payload.get("report_path"),
            "json_report_path": payload.get("json_report_path"),
            "mermaid_path": payload.get("mermaid_path"),
        }
    if command_name == "analyze" and isinstance(payload, dict):
        return {
            "report_path": payload.get("report", {}).get("report_path"),
            "json_report_path": payload.get("report", {}).get("json_report_path"),
            "last_task_path": payload.get("last_task_path"),
            "context_resolution_path": payload.get("machine_outputs", {}).get("context_resolution_path"),
            "seed_candidates_path": payload.get("machine_outputs", {}).get("seed_candidates_path"),
            "next_action_path": payload.get("machine_outputs", {}).get("next_action_path"),
        }
    if command_name == "recommend-tests" and isinstance(payload, dict):
        return {}
    if command_name == "after-edit" and isinstance(payload, dict):
        return {
            "report_path": payload.get("report", {}).get("report_path"),
            "json_report_path": payload.get("report", {}).get("json_report_path"),
            "test_results_path": str((workspace_root / ".ai" / "codegraph" / "test-results.json")),
            "handoff_path": str(runtime_paths(workspace_root)["handoff_latest"]),
            "context_resolution_path": payload.get("machine_outputs", {}).get("context_resolution_path"),
            "next_action_path": payload.get("machine_outputs", {}).get("next_action_path"),
        }
    if command_name == "finish" and isinstance(payload, dict):
        return {
            "report_path": payload.get("report", {}).get("report_path"),
            "json_report_path": payload.get("report", {}).get("json_report_path"),
            "test_results_path": str((workspace_root / ".ai" / "codegraph" / "test-results.json")),
            "handoff_path": str(runtime_paths(workspace_root)["handoff_latest"]),
            "last_task_path": payload.get("last_task_path"),
            "context_resolution_path": payload.get("machine_outputs", {}).get("context_resolution_path"),
            "next_action_path": payload.get("machine_outputs", {}).get("next_action_path"),
        }
    if command_name == "demo":
        return {"workspace_root": str(payload) if isinstance(payload, pathlib.Path) else None}
    if command_name == "export-skill" and isinstance(payload, dict):
        return {"out_dir": payload.get("out_dir")}
    if command_name == "status":
        return {
            "handoff_path": str(runtime_paths(workspace_root)["handoff_latest"]),
            "last_task_path": str(workspace_root / ".ai" / "codegraph" / "last-task.json"),
            "context_resolution_path": str(runtime_paths(workspace_root)["context_resolution"]),
            "build_decision_path": str(runtime_paths(workspace_root)["build_decision"]),
            "next_action_path": str(runtime_paths(workspace_root)["next_action"]),
        }
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

    setup_parser = subparsers.add_parser("setup", help="High-level setup for a copied skill in a real repo")
    setup_parser.add_argument("--workspace-root", default=".")
    setup_parser.add_argument("--profile", default=None)
    setup_parser.add_argument("--project-root", default=None)
    setup_parser.add_argument("--with", dest="with_adapters", action="append", default=[])
    setup_parser.add_argument("--brief", action="store_true", help="Prefer compact output")
    setup_parser.add_argument("--full", action="store_true", help="Prefer fuller output")

    doctor_parser = subparsers.add_parser("doctor", help="Run a lightweight workspace health check")
    doctor_parser.add_argument("--workspace-root", default=".")
    doctor_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    doctor_parser.add_argument("--fix-safe", action="store_true")

    detect_parser = subparsers.add_parser("detect", help="Detect the active adapter")
    detect_parser.add_argument("--workspace-root", default=".")
    detect_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    detect_parser.add_argument("--allow-fallback", action="store_true")

    build_parser = subparsers.add_parser("build", help="Build or refresh the graph")
    build_parser.add_argument("--workspace-root", default=".")
    build_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    build_parser.add_argument("--changed-file", action="append", default=[])
    build_parser.add_argument("--full-rebuild", action="store_true")

    seeds_parser = subparsers.add_parser("seeds", help="List current seeds")
    seeds_parser.add_argument("--workspace-root", default=".")
    seeds_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    report_parser = subparsers.add_parser("report", help="Generate an impact report")
    report_parser.add_argument("--workspace-root", default=".")
    report_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    report_parser.add_argument("--task-id", default=None)
    report_parser.add_argument("--seed", default=None)
    report_parser.add_argument("--changed-file", action="append", default=[])
    report_parser.add_argument("--changed-line", action="append", default=[])
    report_parser.add_argument("--allow-fallback", action="store_true")
    report_parser.add_argument("--max-depth", type=int, default=None)
    report_parser.add_argument("--brief", action="store_true")
    report_parser.add_argument("--full", action="store_true")

    analyze_parser = subparsers.add_parser("analyze", help="High-level build + report command with automatic context")
    analyze_parser.add_argument("--workspace-root", default=".")
    analyze_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    analyze_parser.add_argument("--task-id", default=None)
    analyze_parser.add_argument("--seed", default=None)
    analyze_parser.add_argument("--changed-file", action="append", default=[])
    analyze_parser.add_argument("--changed-line", action="append", default=[])
    analyze_parser.add_argument("--patch-file", default=None)
    analyze_parser.add_argument("--max-depth", type=int, default=None)
    analyze_parser.add_argument("--allow-fallback", action="store_true")
    analyze_parser.add_argument("--brief", action="store_true")
    analyze_parser.add_argument("--full", action="store_true")

    recommend_tests_parser = subparsers.add_parser("recommend-tests", help="Map directly affected test seeds to executable commands")
    recommend_tests_parser.add_argument("--workspace-root", default=".")
    recommend_tests_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    recommend_tests_parser.add_argument("--task-id", required=True)

    integration_parser = subparsers.add_parser("install-integration-pack", help="Install repo-local runtime integration docs and AGENTS managed block")
    integration_parser.add_argument("--workspace-root", default=".")
    integration_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    after_parser = subparsers.add_parser("after-edit", help="Refresh graph, report, evidence, and tests after an edit")
    after_parser.add_argument("--workspace-root", default=".")
    after_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    after_parser.add_argument("--task-id", default=None)
    after_parser.add_argument("--seed", default=None)
    after_parser.add_argument("--changed-file", action="append", default=[])
    after_parser.add_argument("--allow-fallback", action="store_true")
    after_parser.add_argument("--test-scope", choices=["targeted", "configured", "full"], default="configured")
    after_parser.add_argument("--shadow-full", action="store_true")

    finish_parser = subparsers.add_parser("finish", help="High-level after-edit command that reuses recent analyze context")
    finish_parser.add_argument("--workspace-root", default=".")
    finish_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    finish_parser.add_argument("--task-id", default=None)
    finish_parser.add_argument("--seed", default=None)
    finish_parser.add_argument("--changed-file", action="append", default=[])
    finish_parser.add_argument("--patch-file", default=None)
    finish_parser.add_argument("--allow-fallback", action="store_true")
    finish_parser.add_argument("--brief", action="store_true")
    finish_parser.add_argument("--full", action="store_true")
    finish_parser.add_argument("--test-scope", choices=["targeted", "configured", "full"], default="configured")
    finish_parser.add_argument("--shadow-full", action="store_true")

    demo_parser = subparsers.add_parser("demo", help="Run a fixture end-to-end demo")
    demo_parser.add_argument("--fixture", choices=["python_minimal", "tsjs_minimal", "generic_minimal", "tsjs_node_cli", "tsx_react_vite", "sql_pg_minimal", "tsjs_pg_compound"], default="python_minimal")
    demo_parser.add_argument("--workspace", default=None)

    export_parser = subparsers.add_parser("export-skill", help="Export a minimal distribution package")
    export_parser.add_argument("--workspace-root", default=".")
    export_parser.add_argument("--out", required=True)
    export_parser.add_argument("--mode", choices=["consumer", "debug-bundle", "single-folder", "full"], default="consumer")

    status_parser = subparsers.add_parser("status", help="Show current config, recent runs, and handoff state")
    status_parser.add_argument("--workspace-root", default=".")
    status_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    status_parser.add_argument("--brief", action="store_true")
    status_parser.add_argument("--full", action="store_true")

    health_parser = subparsers.add_parser("health", help="Return a compact machine-readable readiness summary")
    health_parser.add_argument("--workspace-root", default=".")
    health_parser.add_argument("--config", default=".code-impact-guardian/config.json")

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
            payload = export_skill(workspace_root=workspace_root, out_dir=pathlib.Path(args.out).resolve(), mode=args.mode)
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
                write_agents_md=True if not hasattr(args, "write_agents_md") else (args.write_agents_md or True),
                write_gitignore=True if not hasattr(args, "write_gitignore") else (args.write_gitignore or True),
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

        if args.command == "setup":
            init_payload = init_workspace(
                workspace_root,
                profile=args.profile,
                project_root=args.project_root,
                with_adapters=args.with_adapters,
                write_agents_md=True,
                write_gitignore=True,
            )
            current_config_path = config_path_for(workspace_root)
            context = command_context(workspace_root, current_config_path)
            doctor = doctor_payload(workspace_root, current_config_path, fix_safe=True)
            if doctor["overall"] == "FAIL":
                error_code = (
                    "SUPPLEMENTAL_ADAPTER_MISSING"
                    if any("sql_postgres enabled but no configured SQL source/test paths were found" in item["message"] for item in doctor["statuses"])
                    else "DOCTOR_FAILED"
                )
                raise CIGUserError(
                    error_code,
                    "Setup completed initialization, but doctor still found a blocking problem.",
                    retryable=True,
                    suggested_next_step="Read TROUBLESHOOTING.md, fix the blocking doctor checks, then rerun `cig.py setup` or `cig.py doctor --fix-safe`.",
                )
            detect = detect_payload(workspace_root, current_config_path)
            payload = {"init": init_payload, "doctor": doctor, "detect": detect}
            warning_count = sum(1 for item in doctor["statuses"] if item["level"] == "WARN")
            event = event_payload(
                command="setup",
                workspace_root=workspace_root,
                project_root=context["project_root"],
                profile=context["profile"],
                primary_adapter=context["primary_adapter"],
                supplemental_adapters=context["supplemental_adapters"],
                task_id=None,
                seed=None,
                status="success",
                output_paths=normalize_output_paths(workspace_root, output_paths_for_command("setup", workspace_root, payload, current_config_path)),
                warning_count=warning_count,
                error_code=None,
                retryable=False,
                suggested_next_step=success_next_step("setup"),
            )
            write_event(workspace_root, event)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        if args.command in {"report", "analyze", "recommend-tests", "after-edit", "finish", "install-integration-pack"}:
            auto_setup_if_missing(workspace_root, config_path)
        if args.command not in {"status", "health"}:
            ensure_config_exists(config_path)
            context = command_context(workspace_root, config_path)
        elif config_path.exists():
            context = command_context(workspace_root, config_path)

        if args.command == "doctor":
            payload = doctor_payload(workspace_root, config_path, fix_safe=args.fix_safe)
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
            payload["fallback_allowed"] = bool(getattr(args, "allow_fallback", False))
            payload["fallback_used"] = bool(payload["detected_adapter"] == "generic" and getattr(args, "allow_fallback", False))
        elif args.command == "build":
            payload = build_graph.build_graph(
                workspace_root=workspace_root,
                config_path=config_path,
                changed_files=args.changed_file,
                force_full=bool(args.full_rebuild),
            )
        elif args.command == "seeds":
            payload = list_seeds.list_seeds(workspace_root=workspace_root, config_path=config_path)
        elif args.command == "report":
            if args.changed_file:
                build_graph.build_graph(
                    workspace_root=workspace_root,
                    config_path=config_path,
                    changed_files=args.changed_file,
                )
            selected_seed, seed_selection = resolve_seed_selection(
                workspace_root=workspace_root,
                config_path=config_path,
                explicit_seed=args.seed,
                changed_files=args.changed_file,
                changed_lines=args.changed_line,
                allow_fallback=args.allow_fallback,
            )
            resolved_task_id = args.task_id or auto_task_id(seed=selected_seed, changed_files=args.changed_file, prefix="report")
            payload = generate_report.generate_report(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=resolved_task_id,
                seed=selected_seed,
                max_depth=args.max_depth,
                mode=requested_report_mode(args, "brief"),
                changed_files=args.changed_file,
            )
            persist_last_task(
                workspace_root,
                command_name="report",
                task_id=resolved_task_id,
                seed=selected_seed,
                changed_files=args.changed_file,
                config_path=config_path,
                context=context,
                report_path=payload.get("report_path"),
                seed_selection=seed_selection,
                build_mode=None,
                fallback_used=seed_selection.get("fallback_used", False),
                report_brief=payload.get("brief"),
                user_summary=payload.get("user_summary"),
                report_completeness=payload.get("report_completeness"),
                test_signal=payload.get("test_signal"),
            )
            payload["task_id"] = resolved_task_id
            payload["seed"] = selected_seed
            payload["seed_selection"] = seed_selection
            task_id = resolved_task_id
            seed = selected_seed
        elif args.command == "analyze":
            payload = run_analyze_command(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=args.task_id,
                seed=args.seed,
                changed_files=args.changed_file,
                changed_lines=args.changed_line,
                max_depth=args.max_depth,
                allow_fallback=args.allow_fallback,
                report_mode=requested_report_mode(args, "brief"),
                patch_file=pathlib.Path(args.patch_file).resolve() if args.patch_file else None,
                stdin_patch=stdin_patch_if_available(),
            )
            task_id = payload["task_id"]
            seed = payload["seed"]
        elif args.command == "recommend-tests":
            payload = after_edit_update.recommend_tests_for_task(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=args.task_id,
            )
            task_id = args.task_id
        elif args.command == "install-integration-pack":
            payload = install_integration_pack(
                workspace_root=workspace_root,
                config_path=config_path,
            )
        elif args.command == "after-edit":
            resolved_task_id, resolved_seed, resolved_changed_files, _, context_resolution = resolve_finish_context(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=args.task_id,
                seed=args.seed,
                changed_files=args.changed_file,
                allow_fallback=args.allow_fallback,
            )
            payload = finalize_after_edit(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=resolved_task_id,
                seed=resolved_seed,
                changed_files=resolved_changed_files,
                command_name="after-edit",
                report_mode="brief",
                context_resolution=context_resolution,
                test_scope=args.test_scope,
                shadow_full=args.shadow_full,
            )
            task_id = resolved_task_id
            seed = resolved_seed
        elif args.command == "finish":
            resolved_task_id, resolved_seed, resolved_changed_files, _, context_resolution = resolve_finish_context(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=args.task_id,
                seed=args.seed,
                changed_files=args.changed_file,
                allow_fallback=args.allow_fallback,
                patch_file=pathlib.Path(args.patch_file).resolve() if args.patch_file else None,
                stdin_patch=stdin_patch_if_available(),
            )
            payload = finalize_after_edit(
                workspace_root=workspace_root,
                config_path=config_path,
                task_id=resolved_task_id,
                seed=resolved_seed,
                changed_files=resolved_changed_files,
                command_name="finish",
                report_mode=requested_report_mode(args, "brief"),
                context_resolution=context_resolution,
                test_scope=args.test_scope,
                shadow_full=args.shadow_full,
            )
            task_id = resolved_task_id
            seed = resolved_seed
        elif args.command == "status":
            payload = status_payload(workspace_root, config_path)
        elif args.command == "health":
            payload = health_payload(workspace_root, config_path)
        else:
            raise CIGUserError(
                "COMMAND_UNHANDLED",
                f"Unhandled command: {args.command}",
                retryable=False,
                suggested_next_step="Use one of the supported commands from cig.py --help.",
            )

        if isinstance(payload, dict):
            task_id = payload.get("task_id", task_id)
            seed = payload.get("seed", seed)
        warning_count = 0
        if isinstance(payload, dict):
            warning_count = len(payload.get("warnings", []))
            warning_count += len((payload.get("build") or {}).get("warnings", []))
            warning_count += len((payload.get("graph") or {}).get("warnings", []))
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
            warning_count=warning_count,
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
