-- Isolated Shiori remote alpha. This database is NOT the local Rust store.
CREATE TABLE IF NOT EXISTS remote_tasks (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
  notes TEXT NOT NULL DEFAULT '',
  project TEXT NOT NULL DEFAULT 'Remote alpha',
  priority TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'todo',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS remote_tasks_scope ON remote_tasks(workspace_id,deleted_at,created_at,id);
CREATE TABLE IF NOT EXISTS remote_dependencies (
  workspace_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  depends_on_id TEXT NOT NULL,
  PRIMARY KEY(workspace_id,task_id,depends_on_id)
);
CREATE TABLE IF NOT EXISTS remote_positions (
  workspace_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  x REAL NOT NULL CHECK(x BETWEEN -1000000 AND 1000000),
  y REAL NOT NULL CHECK(y BETWEEN -1000000 AND 1000000),
  revision INTEGER NOT NULL CHECK(revision > 0),
  PRIMARY KEY(workspace_id,node_id)
);
CREATE TABLE IF NOT EXISTS remote_settings (
  workspace_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision > 0),
  PRIMARY KEY(workspace_id,key)
);
CREATE TABLE IF NOT EXISTS idempotency (
  workspace_id TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  token TEXT NOT NULL,
  request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(workspace_id,operation_id,token)
);
CREATE TABLE IF NOT EXISTS access_limits (
  bucket TEXT NOT NULL,
  window_min INTEGER NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY(bucket,window_min)
);