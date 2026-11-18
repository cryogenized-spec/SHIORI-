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
-- Owner-approved S2 pilot: additive tables, no changes to existing tasks.
-- A pairing records owner intent; device IDs are not authentication tokens.
CREATE TABLE IF NOT EXISTS sync_devices (
  workspace_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  paired_at TEXT NOT NULL,
  revoked_at TEXT,
  PRIMARY KEY(workspace_id,device_id)
);
CREATE TABLE IF NOT EXISTS sync_import_previews (
  proposal_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  local_version INTEGER NOT NULL CHECK(local_version=1),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE INDEX IF NOT EXISTS sync_import_previews_device
  ON sync_import_previews(workspace_id,device_id,task_id);
CREATE TABLE IF NOT EXISTS sync_imports (
  workspace_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  source_version INTEGER NOT NULL,
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  payload_json TEXT NOT NULL,
  receipt_id TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  PRIMARY KEY(workspace_id,task_id),
  UNIQUE(workspace_id,event_id),
  UNIQUE(workspace_id,receipt_id)
);

-- S3 change feed: append-only, sequence-ordered metadata about remote D1
-- changes. Contains no task title, note, attachment or full task body.
-- Existing remote tasks require an explicit baseline manifest snapshot:
-- log installation is NOT a historical backfill.
CREATE TABLE IF NOT EXISTS remote_change_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN
    ('task.insert','task.update','task.delete','task.purge',
     'edge.add','edge.remove')),
  task_id TEXT NOT NULL,
  depends_on_id TEXT,
  task_version INTEGER,
  occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS remote_change_log_scope
  ON remote_change_log(workspace_id,seq);

CREATE TRIGGER IF NOT EXISTS shiori_log_task_insert
AFTER INSERT ON remote_tasks BEGIN
  INSERT INTO remote_change_log(workspace_id,kind,task_id,task_version,occurred_at)
  VALUES(NEW.workspace_id,'task.insert',NEW.id,NEW.version,NEW.updated_at);
END;

CREATE TRIGGER IF NOT EXISTS shiori_log_task_update
AFTER UPDATE ON remote_tasks BEGIN
  INSERT INTO remote_change_log(workspace_id,kind,task_id,task_version,occurred_at)
  VALUES(NEW.workspace_id,
    CASE WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL
      THEN 'task.delete' ELSE 'task.update' END,
    NEW.id,NEW.version,NEW.updated_at);
END;

CREATE TRIGGER IF NOT EXISTS shiori_log_task_purge
AFTER DELETE ON remote_tasks BEGIN
  INSERT INTO remote_change_log(workspace_id,kind,task_id,task_version,occurred_at)
  VALUES(OLD.workspace_id,'task.purge',OLD.id,OLD.version,
    strftime('%Y-%m-%dT%H:%M:%fZ','now'));
END;

CREATE TRIGGER IF NOT EXISTS shiori_log_edge_add
AFTER INSERT ON remote_dependencies BEGIN
  INSERT INTO remote_change_log(workspace_id,kind,task_id,depends_on_id,occurred_at)
  VALUES(NEW.workspace_id,'edge.add',NEW.task_id,NEW.depends_on_id,
    strftime('%Y-%m-%dT%H:%M:%fZ','now'));
END;

CREATE TRIGGER IF NOT EXISTS shiori_log_edge_remove
AFTER DELETE ON remote_dependencies BEGIN
  INSERT INTO remote_change_log(workspace_id,kind,task_id,depends_on_id,occurred_at)
  VALUES(OLD.workspace_id,'edge.remove',OLD.task_id,OLD.depends_on_id,
    strftime('%Y-%m-%dT%H:%M:%fZ','now'));
END;
