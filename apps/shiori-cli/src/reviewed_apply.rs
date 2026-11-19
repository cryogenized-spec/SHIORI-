//! One-task, explicitly reviewed local SQLite apply primitive for the S8
//! owner-controlled orchestrator. NO network, bearer token or automatic sync.
use serde::Deserialize;
use shiori_core::{Priority, TaskStatus};
use shiori_storage::{RemoteCommonFields, SqliteStore};
use std::{error::Error, path::Path};

pub const MAX_REVIEW_BYTES: usize = 16_384;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReviewedInput {
    id: String,
    title: String,
    notes: String,
    project: String,
    priority: Priority,
    status: TaskStatus,
    depends_on: Vec<String>,
}

/// This is deliberately callable only from the opt-in hidden CLI route; it
/// does NOT authenticate a remote snapshot. The Python owner orchestrator
/// must verify original S2 receipt + live S4 content/hash before sending JSON
/// on stdin. A version-pinned local SQL update remains the final CAS.
pub fn apply(
    store: &SqliteStore,
    task_id: &str,
    local_version: i64,
    backup: &Path,
    confirmed: bool,
    content: &[u8],
) -> Result<i64, Box<dyn Error>> {
    if !confirmed {
        return Err("Explicit --confirm-reviewed-snapshot approval required".into());
    }
    if local_version < 1 || content.is_empty() || content.len() > MAX_REVIEW_BYTES {
        return Err("Invalid revision or bounded reviewed-input length".into());
    }
    let parsed: ReviewedInput = serde_json::from_slice(content)
        .map_err(|_| "Malformed or unsupported reviewed common-field payload")?;
    if parsed.id != task_id || parsed.depends_on.len() > 200 {
        return Err("Reviewed task identity or prerequisite budget disagrees".into());
    }
    if parsed.depends_on.windows(2).any(|two| two[0] >= two[1])
        || parsed
            .depends_on
            .iter()
            .any(|id| id == task_id || id.is_empty())
    {
        return Err("Reviewed prerequisites are not strictly ordered".into());
    }
    let local = store.get(task_id)?;
    if local.version != local_version {
        return Err("Local task revision changed after owner's review".into());
    }
    if store.get_dependencies(task_id)? != parsed.depends_on {
        return Err("Local prerequisites changed after owner's review".into());
    }
    let fields = RemoteCommonFields {
        title: &parsed.title,
        notes: &parsed.notes,
        project: &parsed.project,
        priority: parsed.priority,
        status: parsed.status,
    };
    // Backup is made before any possible write; its creation fails closed if
    // the destination already exists, is a symlink or cannot be verified.
    store.backup_private_copy(backup, true)?;
    let result =
        store.apply_remote_common_fields_if_version(task_id, local_version, &fields, true)?;
    Ok(result.version)
}

#[cfg(test)]
mod tests {
    use super::*;
    use shiori_core::{Priority, Task, TaskStatus};
    use std::fs;

    fn task_json(id: &str, notes: &str, depends_on: &[&str]) -> Vec<u8> {
        serde_json::to_vec(&serde_json::json!({
            "id": id, "title": "Remote title", "notes": notes,
            "project": "Cloud", "priority": "urgent",
            "status": "done", "depends_on": depends_on
        }))
        .unwrap()
    }

    #[test]
    fn consent_backup_and_local_cas_preserve_unrelated_fields() {
        let dir = tempfile::tempdir().unwrap();
        let canonical = dir.path().join("tasks.sqlite3");
        let backup = dir.path().join("before.shiori-backup.sqlite3");
        let store = SqliteStore::open(&canonical).unwrap();
        let mut task = Task::new("Local title", "Personal", Priority::Medium, None).unwrap();
        task.estimate_minutes = Some(40);
        task.assignee_id = Some("local".to_owned());
        store.insert(&task).unwrap();
        let body = task_json(&task.id, "PRIVATE remote note", &[]);
        assert!(apply(&store, &task.id, 1, &backup, false, &body).is_err());
        assert!(!backup.exists());
        assert!(apply(&store, &task.id, 2, &backup, true, &body).is_err());
        assert!(!backup.exists());
        let revision = apply(&store, &task.id, 1, &backup, true, &body).unwrap();
        assert_eq!(revision, 2);
        let updated = store.get(&task.id).unwrap();
        assert_eq!(updated.notes, "PRIVATE remote note");
        assert_eq!(updated.title, "Remote title");
        assert_eq!(updated.status, TaskStatus::Done);
        assert_eq!(updated.estimate_minutes, Some(40));
        assert_eq!(updated.assignee_id.as_deref(), Some("local"));
        let former = SqliteStore::open(&backup).unwrap().get(&task.id).unwrap();
        assert_eq!(former.title, "Local title");
        assert_eq!(former.version, 1);
        assert!(apply(&store, &task.id, 1, &backup, true, &body).is_err());
        assert_eq!(store.get(&task.id).unwrap().version, 2);
        assert!(fs::metadata(&backup).unwrap().is_file());
    }

    #[test]
    fn invalid_content_or_edges_cannot_create_backup() {
        let dir = tempfile::tempdir().unwrap();
        let store = SqliteStore::open(dir.path().join("tasks.sqlite3")).unwrap();
        let task = Task::new("Local", "Private", Priority::Medium, None).unwrap();
        store.insert(&task).unwrap();
        let backup = dir.path().join("before.shiori-backup.sqlite3");
        for payload in [
            Vec::new(),
            b"{\"id\":\"untrusted\",\"notes\":\"PRIVATE\"}".to_vec(),
            task_json(&task.id, "PRIVATE", &["z", "a"]),
            task_json(&task.id, "PRIVATE", &[&task.id]),
            vec![b'a'; MAX_REVIEW_BYTES + 1],
        ] {
            assert!(apply(&store, &task.id, 1, &backup, true, &payload).is_err());
            assert!(!backup.exists());
        }
        assert_eq!(store.get(&task.id).unwrap().version, 1);
    }

    #[test]
    fn stale_dependency_graph_refuses_no_write_and_no_backup() {
        let dir = tempfile::tempdir().unwrap();
        let store = SqliteStore::open(dir.path().join("tasks.sqlite3")).unwrap();
        let task = Task::new("Local", "Private", Priority::Low, None).unwrap();
        let dependency = Task::new("Earlier", "Private", Priority::Medium, None).unwrap();
        store.insert(&task).unwrap();
        store.insert(&dependency).unwrap();
        let mut store = store;
        store
            .set_dependencies(&task.id, std::slice::from_ref(&dependency.id))
            .unwrap();
        let backup = dir.path().join("before.shiori-backup.sqlite3");
        let local_version = store.get(&task.id).unwrap().version;
        let body = task_json(&task.id, "Changed", &[]);
        assert!(apply(&store, &task.id, local_version, &backup, true, &body).is_err());
        assert!(!backup.exists());
        assert_eq!(store.get(&task.id).unwrap().version, local_version);
    }
}
