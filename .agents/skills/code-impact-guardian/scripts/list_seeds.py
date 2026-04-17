#!/usr/bin/env python3
import argparse
import json
import pathlib
import sqlite3

from adapters import GENERIC_ADAPTER, detect_language_adapter
from build_graph import graph_paths, load_config, project_root_for


def list_seeds(*, workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    config = load_config(config_path)
    paths = graph_paths(workspace_root, config)
    adapter_name = detect_language_adapter(project_root_for(workspace_root, config), config)
    with sqlite3.connect(paths["db_path"]) as conn:
        file_nodes = [row[0] for row in conn.execute("SELECT node_id FROM nodes WHERE kind = 'file' ORDER BY node_id").fetchall()]
        function_nodes = [row[0] for row in conn.execute("SELECT node_id FROM nodes WHERE kind = 'function' ORDER BY node_id").fetchall()]
        test_nodes = [row[0] for row in conn.execute("SELECT node_id FROM nodes WHERE kind = 'test' ORDER BY node_id").fetchall()]
        rule_nodes = [row[0] for row in conn.execute("SELECT node_id FROM nodes WHERE kind = 'rule' ORDER BY node_id").fetchall()]
    if adapter_name == GENERIC_ADAPTER:
        return {
            "detected_adapter": adapter_name,
            "files": file_nodes,
            "rules": rule_nodes,
        }
    return {
        "detected_adapter": adapter_name,
        "functions": function_nodes,
        "tests": test_nodes,
        "rules": rule_nodes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="List seed candidates from the current graph")
    parser.add_argument("--workspace-root", default=".", help="Workspace root")
    parser.add_argument("--config", default=".code-impact-guardian/config.json", help="Config path")
    args = parser.parse_args()
    workspace_root = pathlib.Path(args.workspace_root).resolve()
    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = (workspace_root / config_path).resolve()
    payload = list_seeds(workspace_root=workspace_root, config_path=config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
