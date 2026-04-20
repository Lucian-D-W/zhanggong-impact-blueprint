import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing

from tests.test_stage11_workflow import build_repo, setup_repo, write_python_repo_with_two_tests
from tests.test_stage15_workflow import analyze_change, load_next_action, run_finish_raw
from tests.test_stage7_workflow import copy_single_skill_folder, run_json


def setup_repo_with_options(
    repo_cig: pathlib.Path,
    repo_root: pathlib.Path,
    *,
    profile: str | None = None,
    extras: list[str] | None = None,
) -> dict:
    command = [
        sys.executable,
        str(repo_cig),
        "setup",
        "--workspace-root",
        str(repo_root),
        "--project-root",
        ".",
    ]
    if profile:
        command.extend(["--profile", profile])
    for extra in extras or []:
        command.extend(["--with", extra])
    return run_json(command, cwd=repo_root)


def graph_db_path(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / ".ai" / "codegraph" / "codegraph.db"


def edge_rows(repo_root: pathlib.Path, edge_type: str | None = None) -> list[dict]:
    sql = """
        SELECT
            e.src_id,
            src.kind,
            src.name,
            src.path,
            e.edge_type,
            e.dst_id,
            dst.kind,
            dst.name,
            dst.path,
            e.confidence,
            e.attrs_json
        FROM edges e
        JOIN nodes src ON src.node_id = e.src_id
        JOIN nodes dst ON dst.node_id = e.dst_id
    """
    params: tuple[str, ...] = ()
    if edge_type:
        sql += " WHERE e.edge_type = ?"
        params = (edge_type,)
    sql += " ORDER BY e.edge_type, e.src_id, e.dst_id"
    with closing(sqlite3.connect(graph_db_path(repo_root))) as conn:
        rows = conn.execute(sql, params).fetchall()
    payload: list[dict] = []
    for row in rows:
        payload.append(
            {
                "src_id": row[0],
                "src_kind": row[1],
                "src_name": row[2],
                "src_path": row[3],
                "edge_type": row[4],
                "dst_id": row[5],
                "dst_kind": row[6],
                "dst_name": row[7],
                "dst_path": row[8],
                "confidence": row[9],
                "attrs": json.loads(row[10] or "{}"),
            }
        )
    return payload


def node_rows(repo_root: pathlib.Path, kind: str | None = None) -> list[dict]:
    sql = "SELECT node_id, kind, name, path, symbol, attrs_json FROM nodes"
    params: tuple[str, ...] = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    sql += " ORDER BY node_id"
    with closing(sqlite3.connect(graph_db_path(repo_root))) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "node_id": row[0],
            "kind": row[1],
            "name": row[2],
            "path": row[3],
            "symbol": row[4],
            "attrs": json.loads(row[5] or "{}"),
        }
        for row in rows
    ]


def report_json(payload: dict) -> dict:
    return json.loads(pathlib.Path(payload["report"]["json_report_path"]).read_text(encoding="utf-8"))


def find_edge(
    repo_root: pathlib.Path,
    *,
    edge_type: str,
    src_kind: str | None = None,
    src_name: str | None = None,
    dst_kind: str | None = None,
    dst_name: str | None = None,
) -> list[dict]:
    matches = []
    for edge in edge_rows(repo_root, edge_type):
        if src_kind and edge["src_kind"] != src_kind:
            continue
        if src_name and edge["src_name"] != src_name:
            continue
        if dst_kind and edge["dst_kind"] != dst_kind:
            continue
        if dst_name and edge["dst_name"] != dst_name:
            continue
        matches.append(edge)
    return matches


def write_node_base(repo_root: pathlib.Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "rules").mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        json.dumps(
            {
                "name": "stage16-contracts",
                "private": True,
                "type": "module",
                "scripts": {"test:node-cli": "node --test"},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_python_env_repo(repo_root: pathlib.Path, *, dynamic: bool = False) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "rules").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    if dynamic:
        app_source = (
            "import os\n\n"
            "def connect(env_name):\n"
            "    return os.environ[env_name]\n"
        )
    else:
        app_source = (
            "import os\n\n"
            "def connect():\n"
            "    return os.getenv('API_URL')\n"
        )
    (repo_root / "src" / "app.py").write_text(app_source, encoding="utf-8")


def write_ts_config_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "config.ts").write_text(
        "const config = { get(key) { return key; } };\n"
        "export function readAuthMode() {\n"
        "  return config.get('auth.mode');\n"
        "}\n",
        encoding="utf-8",
    )


def write_ts_dynamic_env_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "env.ts").write_text(
        "export function readDynamicEnv(envName) {\n"
        "  return process.env[envName];\n"
        "}\n",
        encoding="utf-8",
    )


def write_backend_endpoint_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "server.ts").write_text(
        "const app = { get(path, handler) { return { path, handler }; } };\n"
        "function loginHandler() {\n"
        "  return 'ok';\n"
        "}\n"
        "export function registerAuthRoute() {\n"
        "  return app.get('/api/login', loginHandler);\n"
        "}\n",
        encoding="utf-8",
    )


def write_frontend_endpoint_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "client.ts").write_text(
        "export function submitLogin() {\n"
        "  return fetch('/api/login');\n"
        "}\n",
        encoding="utf-8",
    )


def write_route_component_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "routes.tsx").write_text(
        "export function SettingsForm({ mode }) {\n"
        "  return <section>{mode}</section>;\n"
        "}\n\n"
        "export function SettingsPage() {\n"
        "  return <SettingsForm mode=\"advanced\" />;\n"
        "}\n\n"
        "export const routes = [{ path: '/settings', element: <SettingsPage /> }];\n",
        encoding="utf-8",
    )


def write_nextjs_route_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "app" / "settings").mkdir(parents=True, exist_ok=True)
    (repo_root / "app" / "settings" / "page.tsx").write_text(
        "export default function SettingsPage() {\n"
        "  return <div>Settings</div>;\n"
        "}\n",
        encoding="utf-8",
    )


def write_playwright_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "tests" / "login.spec.ts").write_text(
        "import { test, expect } from '@playwright/test';\n\n"
        "test('login flow', async ({ page }) => {\n"
        "  await page.goto('/login');\n"
        "  await page.evaluate(() => fetch('/api/login'));\n"
        "  await expect(page).toHaveURL('/dashboard');\n"
        "});\n",
        encoding="utf-8",
    )


def write_event_repo(repo_root: pathlib.Path, *, dynamic: bool = False) -> None:
    write_node_base(repo_root)
    if dynamic:
        source = (
            "const emitter = { emit(name, payload) { return { name, payload }; } };\n"
            "export function emitNamed(eventName, payload) {\n"
            "  return emitter.emit(eventName, payload);\n"
            "}\n"
        )
    else:
        source = (
            "const emitter = {\n"
            "  emit(name, payload) { return { name, payload }; },\n"
            "  on(name, handler) { return { name, handler }; },\n"
            "};\n"
            "export function emitAuthChanged(payload) {\n"
            "  return emitter.emit('auth:changed', payload);\n"
            "}\n"
            "export function onAuthChanged(handler) {\n"
            "  return emitter.on('auth:changed', handler);\n"
            "}\n"
        )
    (repo_root / "src" / "events.ts").write_text(source, encoding="utf-8")


def write_ipc_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "ipc.ts").write_text(
        "const ipcRenderer = { send(channel, payload) { return { channel, payload }; } };\n"
        "const ipcMain = { handle(channel, handler) { return { channel, handler }; } };\n"
        "export function sendLogin(payload) {\n"
        "  return ipcRenderer.send('auth:login', payload);\n"
        "}\n"
        "export function handleLogin() {\n"
        "  return ipcMain.handle('auth:login', async () => ({ ok: true }));\n"
        "}\n",
        encoding="utf-8",
    )


def write_sql_repo(repo_root: pathlib.Path, *, include_migration: bool = False) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "db.ts").write_text(
        "const db = { query(sql) { return sql; } };\n"
        "export function loadUsers() {\n"
        "  return db.query('SELECT users.id FROM users JOIN sessions ON sessions.user_id = users.id');\n"
        "}\n"
        "export function updateUsers() {\n"
        "  return db.query(\"UPDATE users SET name = 'demo'\");\n"
        "}\n",
        encoding="utf-8",
    )
    if include_migration:
        (repo_root / "migrations").mkdir(parents=True, exist_ok=True)
        (repo_root / "migrations" / "001_users.sql").write_text(
            "CREATE TABLE users (\n"
            "  id text primary key,\n"
            "  name text not null\n"
            ");\n"
            "ALTER TABLE users ADD COLUMN email text;\n",
            encoding="utf-8",
        )


def write_obsidian_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "commands.ts").write_text(
        "export function registerDaily(app) {\n"
        "  return this.addCommand({ id: 'open-daily-note', name: 'Open Daily Note', callback() {} });\n"
        "}\n"
        "export function runDaily(app) {\n"
        "  return app.commands.executeCommandById('open-daily-note');\n"
        "}\n",
        encoding="utf-8",
    )


def write_dynamic_component_repo(repo_root: pathlib.Path) -> None:
    write_node_base(repo_root)
    (repo_root / "src" / "dynamic.tsx").write_text(
        "export function Dashboard({ Current }) {\n"
        "  return <Current />;\n"
        "}\n",
        encoding="utf-8",
    )


def break_login_behavior(repo_root: pathlib.Path) -> None:
    (repo_root / "src" / "app.py").write_text(
        "import os\n\n"
        "def login(user_name, password):\n"
        "    return {'ok': False, 'message': 'broken', 'env': os.getenv('API_URL')}\n",
        encoding="utf-8",
    )


class Stage16WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = pathlib.Path(__file__).resolve().parents[1]
        cls.cig_script = cls.repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
        cls.export_tmp = tempfile.TemporaryDirectory()
        cls.single_export = pathlib.Path(cls.export_tmp.name) / "single-folder-export"
        run_json(
            [
                sys.executable,
                str(cls.cig_script),
                "export-skill",
                "--workspace-root",
                str(cls.repo_root),
                "--out",
                str(cls.single_export),
                "--mode",
                "single-folder",
            ],
            cwd=cls.repo_root,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.export_tmp.cleanup()

    def test_env_contract_links_function_to_env_var(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "env-contract"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_env_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="READS_ENV",
                    src_kind="function",
                    src_name="connect",
                    dst_kind="env_var",
                    dst_name="API_URL",
                )
            )

    def test_config_contract_links_function_to_config_key(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "config-contract"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ts_config_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="READS_CONFIG",
                    src_kind="function",
                    src_name="readAuthMode",
                    dst_kind="config_key",
                    dst_name="auth.mode",
                )
            )

    def test_dynamic_env_key_uses_low_confidence_depends_on(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "dynamic-env"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ts_dynamic_env_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            dynamic_edges = [
                edge
                for edge in find_edge(
                    repo_root,
                    edge_type="DEPENDS_ON",
                    src_kind="function",
                    src_name="readDynamicEnv",
                    dst_kind="env_var",
                )
                if edge["confidence"] <= 0.65 and edge["attrs"].get("dependency_kind") == "env_read"
            ]
            self.assertTrue(dynamic_edges)

    def test_backend_endpoint_definition_creates_endpoint_node(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "backend-endpoint"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_backend_endpoint_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            endpoint_nodes = [node for node in node_rows(repo_root, "endpoint") if node["name"] == "/api/login"]
            self.assertTrue(endpoint_nodes)

    def test_frontend_fetch_links_to_endpoint(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "frontend-endpoint"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_frontend_endpoint_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="USES_ENDPOINT",
                    src_kind="function",
                    src_name="submitLogin",
                    dst_kind="endpoint",
                    dst_name="/api/login",
                )
            )

    def test_react_route_links_to_component(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "route-component"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_route_component_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="ROUTES_TO",
                    src_kind="route",
                    src_name="/settings",
                    dst_kind="component",
                    dst_name="SettingsPage",
                )
            )

    def test_nextjs_file_path_creates_route(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "next-route"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_nextjs_route_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            routes = [node for node in node_rows(repo_root, "route") if node["name"] == "/settings"]
            self.assertTrue(routes)

    def test_playwright_flow_links_to_route_and_endpoint(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "playwright-flow"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_playwright_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="ROUTES_TO",
                    src_kind="playwright_flow",
                    src_name="login flow",
                    dst_kind="route",
                    dst_name="/login",
                )
            )
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="USES_ENDPOINT",
                    src_kind="playwright_flow",
                    src_name="login flow",
                    dst_kind="endpoint",
                    dst_name="/api/login",
                )
            )

    def test_component_renders_child_component(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "component-render"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_route_component_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="RENDERS_COMPONENT",
                    src_kind="component",
                    src_name="SettingsPage",
                    dst_kind="component",
                    dst_name="SettingsForm",
                )
            )

    def test_component_uses_props(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "component-prop"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_route_component_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="USES_PROP",
                    src_kind="component",
                    src_name="SettingsForm",
                    dst_kind="prop",
                    dst_name="mode",
                )
            )

    def test_route_component_prop_chain_appears_in_report(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "route-chain-report"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_route_component_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/routes.tsx:SettingsPage",
                changed_files=["src/routes.tsx"],
            )
            chains = [chain for chain in report_json(payload).get("architecture_chains", []) if chain.get("chain_type") == "route_component_prop"]
            self.assertTrue(chains)
            rendered = json.dumps(chains[0], ensure_ascii=False)
            self.assertIn("/settings", rendered)
            self.assertIn("SettingsPage", rendered)
            self.assertIn("mode", rendered)

    def test_event_emit_and_handler_share_event_node(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "event-graph"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_event_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            emit_edges = find_edge(
                repo_root,
                edge_type="EMITS_EVENT",
                src_kind="function",
                src_name="emitAuthChanged",
                dst_kind="event",
                dst_name="auth:changed",
            )
            handle_edges = find_edge(
                repo_root,
                edge_type="HANDLES_EVENT",
                src_kind="function",
                src_name="onAuthChanged",
                dst_kind="event",
                dst_name="auth:changed",
            )
            self.assertTrue(emit_edges)
            self.assertTrue(handle_edges)
            self.assertEqual(emit_edges[0]["dst_id"], handle_edges[0]["dst_id"])

    def test_dynamic_event_name_uses_low_confidence_depends_on(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "dynamic-event"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_event_repo(repo_root, dynamic=True)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            edges = [
                edge
                for edge in find_edge(
                    repo_root,
                    edge_type="DEPENDS_ON",
                    src_kind="function",
                    src_name="emitNamed",
                    dst_kind="event",
                )
                if edge["confidence"] <= 0.65 and edge["attrs"].get("dependency_kind") == "event_emit"
            ]
            self.assertTrue(edges)

    def test_electron_ipc_send_and_handle_are_linked(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "ipc-graph"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ipc_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            send_edges = find_edge(
                repo_root,
                edge_type="IPC_SENDS",
                src_kind="function",
                src_name="sendLogin",
                dst_kind="ipc_channel",
                dst_name="auth:login",
            )
            handle_edges = find_edge(
                repo_root,
                edge_type="IPC_HANDLES",
                src_kind="function",
                src_name="handleLogin",
                dst_kind="ipc_channel",
                dst_name="auth:login",
            )
            self.assertTrue(send_edges)
            self.assertTrue(handle_edges)
            self.assertEqual(send_edges[0]["dst_id"], handle_edges[0]["dst_id"])

    def test_sql_query_and_mutation_edges(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "sql-graph"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_sql_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="QUERIES_TABLE",
                    src_kind="function",
                    src_name="loadUsers",
                    dst_kind="sql_table",
                    dst_name="users",
                )
            )
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="QUERIES_TABLE",
                    src_kind="function",
                    src_name="loadUsers",
                    dst_kind="sql_table",
                    dst_name="sessions",
                )
            )
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="MUTATES_TABLE",
                    src_kind="function",
                    src_name="updateUsers",
                    dst_kind="sql_table",
                    dst_name="users",
                )
            )

    def test_sql_migration_escalates_to_B4(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "sql-migration-budget"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_sql_repo(repo_root, include_migration=True)
            setup_repo_with_options(repo_cig, repo_root, profile="node-cli", extras=["sql-postgres"])
            build_repo(repo_cig, repo_root)
            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="file:migrations/001_users.sql",
                changed_files=["migrations/001_users.sql"],
            )
            self.assertEqual(load_next_action(payload)["verification_budget"], "B4")

    def test_obsidian_command_registration_and_invocation_link(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "obsidian-commands"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_obsidian_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            self.assertTrue(
                find_edge(
                    repo_root,
                    edge_type="REGISTER_COMMAND",
                    src_kind="function",
                    src_name="registerDaily",
                    dst_kind="obsidian_command",
                    dst_name="open-daily-note",
                )
            )
            invoke_edges = [
                edge
                for edge in find_edge(
                    repo_root,
                    edge_type="DEPENDS_ON",
                    src_kind="function",
                    src_name="runDaily",
                    dst_kind="obsidian_command",
                    dst_name="open-daily-note",
                )
                if edge["attrs"].get("dependency_kind") == "command_use"
            ]
            self.assertTrue(invoke_edges)

    def test_generic_depends_on_is_used_when_relationship_type_is_uncertain(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "generic-depends"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_dynamic_component_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            edges = [
                edge
                for edge in find_edge(
                    repo_root,
                    edge_type="DEPENDS_ON",
                    src_kind="component",
                    src_name="Dashboard",
                    dst_kind="component",
                )
                if edge["confidence"] <= 0.65 and edge["attrs"].get("dependency_kind") == "component_render"
            ]
            self.assertTrue(edges)

    def test_next_action_lists_affected_contracts_and_architecture_chains(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "next-action-contracts"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_ipc_repo(repo_root)
            setup_repo(repo_cig, repo_root, profile="node-cli")
            build_repo(repo_cig, repo_root)
            payload = analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/ipc.ts:sendLogin",
                changed_files=["src/ipc.ts"],
            )
            next_action = load_next_action(payload)
            self.assertTrue(next_action.get("affected_contracts"))
            self.assertTrue(next_action.get("architecture_chains"))
            self.assertIn(next_action.get("contract_risk"), {"low", "medium", "high"})
            self.assertIn(next_action.get("contract_confidence"), {"low", "medium", "high"})

    def test_loop_breaker_report_includes_contract_chain_after_repeated_failures(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo_root = pathlib.Path(tmp) / "loop-breaker-contracts"
            repo_cig = copy_single_skill_folder(self.single_export, repo_root)
            write_python_repo_with_two_tests(repo_root)
            setup_repo(repo_cig, repo_root, profile="python-basic")
            (repo_root / "src" / "app.py").write_text(
                "import os\n\n"
                "def login(user_name, password):\n"
                "    if not user_name or not password:\n"
                "        return {'ok': False, 'message': 'missing', 'env': os.getenv('API_URL')}\n"
                "    return {'ok': True, 'message': 'baseline', 'env': os.getenv('API_URL')}\n",
                encoding="utf-8",
            )
            analyze_change(
                repo_cig,
                repo_root,
                seed="fn:src/app.py:login",
                changed_files=["src/app.py"],
            )
            break_login_behavior(repo_root)
            for _ in range(4):
                result = run_finish_raw(repo_cig, repo_root, changed_files=["src/app.py"], test_scope="targeted")
                self.assertNotEqual(result.returncode, 0)
            loop_breaker = json.loads((repo_root / ".ai" / "codegraph" / "loop-breaker-report.json").read_text(encoding="utf-8"))
            self.assertIn("contract_chain", loop_breaker)
            self.assertIn("env_vars", loop_breaker["contract_chain"])
            self.assertTrue(loop_breaker["contract_chain"]["env_vars"])


if __name__ == "__main__":
    unittest.main()

