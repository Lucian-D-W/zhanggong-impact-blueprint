PRAGMA foreign_keys = ON;

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
    'USES_PROP', 'REGISTER_COMMAND', 'IPC_SENDS', 'IPC_HANDLES',
    'DEPENDS_ON', 'EXPOSES_ENDPOINT', 'USES_ENDPOINT'
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
  ('schema_version', '4'),
  ('graph_mode', 'direct-edges-only')
ON CONFLICT(meta_key) DO UPDATE SET meta_value = excluded.meta_value;
