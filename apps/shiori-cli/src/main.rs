//! A small local-only client for exercising the same Rust domain and storage layers
//! that future desktop, Android, API and MCP adapters will call.
use clap::{Parser, Subcommand};
use jiff::{
    Timestamp, ZonedDateTime,
    civil::{Date, Time},
    fmt::strtime,
    tz::Offset,
};
use shiori_core::scheduling::{Interval, PlanRequest, PlanningTask, UnscheduledReason, plan_day};
use shiori_core::{
    Priority, Task, TaskPatch, TaskStatus, utc_rfc3339, validate_assignee_id, validate_estimate,
};
use shiori_storage::{SpatialViewStore, SqliteStore, SyncJournal, TaskFilter};
use std::{
    error::Error,
    io::{self, Write},
    path::PathBuf,
};

#[derive(Parser)]
#[command(name = "shiori", version, about = "SHIORI — offline task management")]
struct Args {
    /// SQLite database. Defaults to $XDG_DATA_HOME/shiori/tasks.sqlite3
    #[arg(long, env = "SHIORI_DB")]
    database: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Create a task
    Add {
        title: String,
        #[arg(long, default_value = "Inbox")]
        project: String,
        #[arg(long, default_value = "medium")]
        priority: Priority,
        /// Due calendar day (YYYY-MM-DD)
        #[arg(long)]
        due: Option<Date>,
        /// Expected effort for this task, in minutes (1–1440)
        #[arg(long)]
        minutes: Option<i64>,
        /// Optional task notes
        #[arg(long, default_value = "")]
        notes: String,
        /// Local assignment identity (not authentication)
        #[arg(long, default_value = "local")]
        assign_to: String,
    },
    /// List tasks, optionally filtered
    List {
        #[arg(long)]
        project: Option<String>,
        #[arg(long)]
        status: Option<TaskStatus>,
        #[arg(long)]
        search: Option<String>,
    },
    /// Local-only urgent, due and in-progress tasks (assignment is not yet supported)
    Attention {
        #[arg(long)]
        on: Option<Date>,
    },
    /// Preview one workday's time blocks without modifying tasks
    Plan {
        date: Date,
        #[arg(long, default_value = "08:00", value_parser = parse_clock)]
        start: Time,
        #[arg(long, default_value = "17:00", value_parser = parse_clock)]
        end: Time,
        #[arg(long, requires = "break_end", value_parser = parse_clock)]
        break_start: Option<Time>,
        #[arg(long, requires = "break_start", value_parser = parse_clock)]
        break_end: Option<Time>,
        /// Local wall-clock UTC offset in minutes (120 means UTC+02:00).
        /// This preview does not yet implement named timezones or DST.
        #[arg(long, default_value_t = 120)]
        utc_offset_minutes: i32,
        /// Fallback estimate when a task has no saved duration (1–1440)
        #[arg(long, default_value_t = 30)]
        default_minutes: i64,
    },
    /// Replace a task's prerequisites. Use --clear to remove all.
    Depends {
        id: String,
        /// Prerequisite task ID; repeat for more than one
        #[arg(long = "on", conflicts_with = "clear")]
        on: Vec<String>,
        /// Clear all prerequisites
        #[arg(long)]
        clear: bool,
    },
    /// View one task by its ID
    Show { id: String },
    /// Change a task's status, including in progress
    Status { id: String, status: TaskStatus },
    /// Private length-prefixed machine protocol for the local development UI
    #[command(hide = true)]
    BridgeDump,
    /// Local-only indexed assignment snapshot with blocker state
    #[command(hide = true)]
    BridgeAttention,
    /// Read-only spatial view positions; versioned independently from tasks.
    #[command(hide = true)]
    BridgeSpatial,
    /// Read-only actual dependency links (prerequisite -> dependent).
    #[command(hide = true)]
    BridgeEdges,
    /// Read-only, content-free native task and dependency identity manifest.
    #[command(hide = true)]
    BridgeManifest,
    /// Stage an exact native task revision into a durable local sync journal.
    /// This command NEVER calls Cloudflare or uploads task contents.
    SyncStage {
        id: String,
        /// Required optimistic revision from `show` or a previous edit.
        #[arg(long)]
        if_version: i64,
        /// Optional isolated journal database (defaults beside canonical tasks).
        #[arg(long)]
        journal: Option<PathBuf>,
    },
    /// Inspect the local sync queue without printing task contents or notes.
    SyncQueue {
        #[arg(long)]
        journal: Option<PathBuf>,
    },
    /// Mark an event acknowledged only after a separate client verifies a
    /// matching authenticated remote import receipt. No network is performed.
    SyncAck {
        event_id: String,
        #[arg(long)]
        remote_id: String,
        #[arg(long)]
        remote_revision: i64,
        #[arg(long)]
        local_task_id: String,
        #[arg(long)]
        local_revision: i64,
        #[arg(long)]
        journal: Option<PathBuf>,
    },
    /// Create a new private, integrity-checked canonical SQLite snapshot.
    /// Never uploads, overwrites an old backup, or changes any task.
    SyncBackup {
        /// A NEW private filename ending in .shiori-backup.sqlite3
        #[arg(long)]
        to: PathBuf,
        /// Explicitly consent to a second copy containing task titles/notes.
        #[arg(long)]
        confirm_private_copy: bool,
    },
    /// Update only a task's visual placement, guarded by its view revision.
    #[command(hide = true)]
    SpatialSet {
        id: String,
        x: f64,
        y: f64,
        #[arg(long)]
        if_revision: i64,
    },
    /// Complete a task
    Done { id: String },
    /// Reopen a task
    Reopen { id: String },
    /// Rename a task
    Rename { id: String, title: String },
    /// Edit task fields; omit a flag to leave that field unchanged
    Edit {
        id: String,
        #[arg(long)]
        title: Option<String>,
        #[arg(long)]
        notes: Option<String>,
        #[arg(long)]
        project: Option<String>,
        #[arg(long)]
        priority: Option<Priority>,
        /// Set a due date (YYYY-MM-DD)
        #[arg(long, conflicts_with = "clear_due")]
        due: Option<Date>,
        /// Remove the current due date
        #[arg(long)]
        clear_due: bool,
        /// Expected effort in minutes (1–1440)
        #[arg(long, conflicts_with = "clear_minutes")]
        minutes: Option<i64>,
        /// Clear the saved effort estimate
        #[arg(long)]
        clear_minutes: bool,
        /// Reject if the task changed since this revision was read
        #[arg(long)]
        if_version: Option<i64>,
        /// Set local assignee identity
        #[arg(long, conflicts_with = "unassign")]
        assign_to: Option<String>,
        /// Clear assignment
        #[arg(long)]
        unassign: bool,
    },
    /// Soft-delete a task (retains a tombstone)
    Remove {
        id: String,
        /// Reject a stale delete from another UI or process
        #[arg(long)]
        if_version: Option<i64>,
    },
}

fn parse_clock(raw: &str) -> Result<Time, String> {
    Time::strptime("%H:%M", raw).map_err(|e| e.to_string())
}

fn default_database() -> Result<PathBuf, Box<dyn Error>> {
    if let Some(base) = std::env::var_os("XDG_DATA_HOME") {
        return Ok(PathBuf::from(base).join("shiori/tasks.sqlite3"));
    }
    let home =
        std::env::var_os("HOME").ok_or("HOME or XDG_DATA_HOME must be set, or pass --database")?;
    Ok(PathBuf::from(home).join(".local/share/shiori/tasks.sqlite3"))
}

/// Length-prefixed UTF-8 fields (11 per record); framing supports arbitrary
/// notes/newlines and does not depend on error-prone text table parsing.
fn bridge_dump(tasks: &[Task]) -> Result<(), Box<dyn Error>> {
    let stdout = io::stdout();
    let mut out = io::BufWriter::new(stdout.lock());
    out.write_all(b"SHIORI-BRIDGE-2\n")?;
    for task in tasks {
        let fields = [
            task.id.clone(),
            task.title.clone(),
            task.notes.clone(),
            task.project.clone(),
            task.priority.as_str().to_owned(),
            task.status.as_str().to_owned(),
            task.due_on.map(|d| d.to_string()).unwrap_or_default(),
            utc_rfc3339(task.created_at),
            utc_rfc3339(task.updated_at),
            task.estimate_minutes
                .map(|n| n.to_string())
                .unwrap_or_default(),
            task.version.to_string(),
            task.assignee_id.clone().unwrap_or_default(),
        ];
        for field in &fields {
            out.write_all(&u32::try_from(field.len())?.to_be_bytes())?;
            out.write_all(field.as_bytes())?;
        }
    }
    out.flush()?;
    Ok(())
}

/// Separate indexed attention export; each record has the full task snapshot
/// plus a final blocked flag, so the client cannot guess prerequisite state.
fn bridge_attention(items: &[(Task, bool)]) -> Result<(), Box<dyn Error>> {
    let stdout = io::stdout();
    let mut out = io::BufWriter::new(stdout.lock());
    out.write_all(b"SHIORI-ATTENTION-1\n")?;
    for (task, blocked) in items {
        let fields = [
            task.id.clone(),
            task.title.clone(),
            task.notes.clone(),
            task.project.clone(),
            task.priority.as_str().to_owned(),
            task.status.as_str().to_owned(),
            task.due_on.map(|date| date.to_string()).unwrap_or_default(),
            utc_rfc3339(task.created_at),
            utc_rfc3339(task.updated_at),
            task.estimate_minutes
                .map(|minutes| minutes.to_string())
                .unwrap_or_default(),
            task.version.to_string(),
            task.assignee_id.clone().unwrap_or_default(),
            blocked.to_string(),
        ];
        for field in &fields {
            out.write_all(&u32::try_from(field.len())?.to_be_bytes())?;
            out.write_all(field.as_bytes())?;
        }
    }
    out.flush()?;
    Ok(())
}

/// Private length-prefixed machine snapshots shared with the localhost
/// development bridge. Never parse task metadata by splitting on newlines.
fn bridge_rows(marker: &[u8], rows: &[Vec<String>]) -> Result<(), Box<dyn Error>> {
    let stdout = io::stdout();
    let mut out = io::BufWriter::new(stdout.lock());
    out.write_all(marker)?;
    for row in rows {
        for field in row {
            out.write_all(&u32::try_from(field.len())?.to_be_bytes())?;
            out.write_all(field.as_bytes())?;
        }
    }
    out.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = Args::parse();
    let path = match args.database {
        Some(path) => path,
        None => default_database()?,
    };
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let spatial_path = path.with_extension("isw.sqlite3");
    let default_journal_path = path.with_extension("sync.sqlite3");
    let mut store = SqliteStore::open(path)?;
    match args.command {
        Command::Add {
            title,
            project,
            priority,
            due,
            minutes,
            notes,
            assign_to,
        } => {
            let mut task = Task::new(&title, &project, priority, due)?;
            task.estimate_minutes = minutes.map(validate_estimate).transpose()?;
            task.assignee_id = Some(validate_assignee_id(&assign_to)?);
            task.notes = notes;
            store.insert(&task)?;
            println!("Created {} [{}]", task.title, task.id);
        }
        Command::List {
            project,
            status,
            search,
        } => {
            for task in store.list(TaskFilter {
                project: project.as_deref(),
                status,
                search: search.as_deref(),
                ..Default::default()
            })? {
                println!(
                    "{}  {:11} {:8} {}  {}",
                    task.id,
                    task.status.as_str(),
                    task.priority.as_str(),
                    task.due_on
                        .map(|d| d.to_string())
                        .unwrap_or_else(|| "          ".into()),
                    task.title
                );
            }
        }
        Command::Attention { on } => {
            let today = on.unwrap_or_else(|| ZonedDateTime::now().date());
            println!("LOCAL ATTENTION · {today} · due, high priority or in progress");
            println!("Assignment-aware attention requires the future identity model.");
            for task in store.list(TaskFilter::default())?.iter().filter(|task| {
                task.status != TaskStatus::Done
                    && (task.due_on.is_some_and(|due| due <= today)
                        || matches!(task.priority, Priority::High | Priority::Urgent)
                        || task.status == TaskStatus::InProgress)
            }) {
                println!(
                    "{}  {:11} {:8} {}",
                    task.id,
                    task.status.as_str(),
                    task.priority.as_str(),
                    task.title
                );
            }
        }
        Command::Plan {
            date,
            start,
            end,
            break_start,
            break_end,
            utc_offset_minutes,
            default_minutes,
        } => {
            let seconds = utc_offset_minutes
                .checked_mul(60)
                .ok_or("UTC offset minutes overflow")?;
            if seconds.abs() >= 86_400 {
                return Err("UTC offset minutes must fit within a day".into());
            }
            let offset = Offset::from_seconds(seconds)?;
            let zone = offset.to_time_zone();
            let local_to_utc = |clock: Time| -> Result<Timestamp, Box<dyn Error>> {
                Ok(date
                    .to_datetime(clock)
                    .to_zoned_datetime(zone.clone())?
                    .timestamp())
            };
            let availability = vec![Interval::new(local_to_utc(start)?, local_to_utc(end)?)?];
            let busy = match (break_start, break_end) {
                (Some(from), Some(to)) => {
                    vec![Interval::new(local_to_utc(from)?, local_to_utc(to)?)?]
                }
                (None, None) => Vec::new(),
                _ => return Err("provide both break-start and break-end".into()),
            };
            validate_estimate(default_minutes)?;
            let all = store.list(TaskFilter::default())?;
            let completed_ids: Vec<String> = all
                .iter()
                .filter(|task| task.status == TaskStatus::Done)
                .map(|task| task.id.clone())
                .collect();
            let pending: Vec<PlanningTask> = all
                .into_iter()
                .filter(|task| task.status != TaskStatus::Done)
                .map(|task| {
                    Ok(PlanningTask {
                        dependencies: store.get_dependencies(&task.id)?,
                        minutes: task.estimate_minutes.unwrap_or(default_minutes),
                        id: task.id,
                        title: task.title,
                        priority: task.priority,
                        due_on: task.due_on,
                    })
                })
                .collect::<Result<_, shiori_storage::StorageError>>()?;
            let result = plan_day(PlanRequest {
                day: date,
                tasks: pending,
                completed_ids,
                availability,
                busy,
            })?;
            println!("PREVIEW ONLY · {date} · fixed UTC offset {utc_offset_minutes} minutes");
            println!(
                "Saved task estimates are used; missing estimates fall back to {default_minutes} minutes."
            );
            println!(
                "Saved prerequisite links are respected; missing/deleted prerequisites remain blocked."
            );
            println!("No task or calendar events were written.");
            for block in &result.blocks {
                println!(
                    "{}–{}  {}{}",
                    strtime::format("%H:%M", &block.start.to_zoned_datetime(zone.clone()))?,
                    strtime::format("%H:%M", &block.end.to_zoned_datetime(zone.clone()))?,
                    block.title,
                    if block.overdue { " [OVERDUE]" } else { "" }
                );
            }
            for item in &result.unscheduled {
                let reason = match item.reason {
                    UnscheduledReason::NoCapacity => "no available time",
                    UnscheduledReason::BlockedByDependency => "blocked by dependency",
                };
                println!("UNSCHEDULED {} · {}", item.task_id, reason);
            }
        }
        Command::Depends { id, on, clear } => {
            if !clear && on.is_empty() {
                return Err("pass one or more --on task IDs, or use --clear".into());
            }
            let updated = store.set_dependencies(&id, &on)?;
            println!(
                "Updated prerequisites for {} [revision {}]",
                updated.title, updated.version
            );
            println!("Prerequisites: {}", store.get_dependencies(&id)?.join(", "));
        }
        Command::SyncStage {
            id,
            if_version,
            journal,
        } => {
            let task = store.get_including_deleted(&id)?;
            if task.version != if_version {
                return Err(format!(
                    "Task changed: expected revision {if_version}, current revision {}",
                    task.version
                )
                .into());
            }
            let depends_on = if task.deleted_at.is_none() {
                store.get_dependencies(&id)?
            } else {
                Vec::new()
            };
            let mut outbox = SyncJournal::open(journal.unwrap_or(default_journal_path))?;
            let (item, created) = outbox.stage(&task, &depends_on)?;
            println!(
                "{} local event {} (task {}, revision {}). No network request or upload was made.",
                if created { "Staged" } else { "Already staged" },
                item.event_id,
                item.task_id,
                item.local_version
            );
        }
        Command::SyncQueue { journal } => {
            let outbox = SyncJournal::open(journal.unwrap_or(default_journal_path))?;
            let items = outbox.list(500)?;
            println!(
                "Local device {}, {} queue entries. Nothing uploaded.",
                outbox.device_id(),
                items.len()
            );
            for item in items {
                println!(
                    "{} {} revision {} status {}",
                    item.event_id, item.task_id, item.local_version, item.state
                );
            }
        }
        Command::SyncAck {
            event_id,
            remote_id,
            remote_revision,
            local_task_id,
            local_revision,
            journal,
        } => {
            if remote_id != local_task_id || remote_revision != 1 || local_revision != 1 {
                return Err(
                    "S2 pilot requires identical canonical IDs and initial revision 1".into(),
                );
            }
            let current = store.get_including_deleted(&local_task_id)?;
            if current.deleted_at.is_some() || current.version != local_revision {
                return Err(
                    "Canonical local task changed after staging; keep the event pending for review"
                        .into(),
                );
            }
            let mut outbox = SyncJournal::open(journal.unwrap_or(default_journal_path))?;
            let changed = outbox.acknowledge(
                &event_id,
                &remote_id,
                remote_revision,
                &local_task_id,
                local_revision,
            )?;
            println!(
                "{} verified remote receipt for {} (remote revision {}).",
                if changed {
                    "Acknowledged"
                } else {
                    "Already acknowledged"
                },
                event_id,
                remote_revision
            );
        }
        Command::BridgeDump => bridge_dump(&store.list(TaskFilter::default())?)?,
        Command::BridgeAttention => {
            bridge_attention(&store.assigned_attention("local")?)?;
        }
        Command::BridgeSpatial => {
            let rows: Vec<Vec<String>> = SpatialViewStore::open(&spatial_path)?
                .positions()?
                .into_iter()
                .map(|p| {
                    vec![
                        p.task_id,
                        p.x.to_string(),
                        p.y.to_string(),
                        p.revision.to_string(),
                    ]
                })
                .collect();
            bridge_rows(b"SHIORI-SPATIAL-1\n", &rows)?;
        }
        Command::BridgeEdges => {
            let rows: Vec<Vec<String>> = store
                .spatial_dependency_edges()?
                .into_iter()
                .map(|(from, to)| vec![from, to])
                .collect();
            bridge_rows(b"SHIORI-EDGES-1\n", &rows)?;
        }
        Command::BridgeManifest => {
            // This is a LOCAL-only read. No names, notes, API keys, attachments,
            // remote requests, or sync writes; include tombstones for reconciliation.
            let mut tasks = store.list(TaskFilter {
                include_deleted: true,
                ..Default::default()
            })?;
            tasks.sort_by(|a, b| a.id.cmp(&b.id));
            let rows: Vec<Vec<String>> = tasks
                .iter()
                .map(|task| {
                    let dependencies = if task.deleted_at.is_none() {
                        store.get_dependencies(&task.id)?
                    } else {
                        Vec::new()
                    };
                    Ok(vec![
                        task.id.clone(),
                        task.version.to_string(),
                        task.status.as_str().to_owned(),
                        utc_rfc3339(task.updated_at),
                        task.deleted_at.map(utc_rfc3339).unwrap_or_default(),
                        dependencies.join(","),
                    ])
                })
                .collect::<Result<_, shiori_storage::StorageError>>()?;
            bridge_rows(b"SHIORI-MANIFEST-1\n", &rows)?;
        }
        Command::SyncBackup {
            to,
            confirm_private_copy,
        } => {
            store.backup_private_copy(&to, confirm_private_copy)?;
            println!("Private SQLite snapshot created and verified. Canonical tasks unchanged.");
        }
        Command::SpatialSet {
            id,
            x,
            y,
            if_revision,
        } => {
            let mut view = SpatialViewStore::open(&spatial_path)?;
            let p = view.set_position(&store, &id, x, y, if_revision)?;
            println!("{} {} {} {}", p.task_id, p.x, p.y, p.revision);
        }
        Command::Status { id, status } => {
            println!("Updated {}", store.set_status(&id, status)?.title);
        }
        Command::Show { id } => {
            let task = store.get(&id)?;
            println!("{task:#?}");
            if let Some(minutes) = task.estimate_minutes {
                println!("Estimated effort: {minutes} minutes");
            } else {
                println!("Estimated effort: not set");
            }
            println!("Prerequisites: {:?}", store.get_dependencies(&id)?);
        }
        Command::Done { id } => println!(
            "Completed {}",
            store.set_status(&id, TaskStatus::Done)?.title
        ),
        Command::Reopen { id } => println!(
            "Reopened {}",
            store.set_status(&id, TaskStatus::Todo)?.title
        ),
        Command::Rename { id, title } => {
            println!("Renamed to {}", store.rename(&id, &title)?.title)
        }
        Command::Edit {
            id,
            title,
            notes,
            project,
            priority,
            due,
            clear_due,
            minutes,
            clear_minutes,
            if_version,
            assign_to,
            unassign,
        } => {
            let patch = TaskPatch {
                title,
                notes,
                project,
                priority,
                due_on: if clear_due { Some(None) } else { due.map(Some) },
                estimate_minutes: if clear_minutes {
                    Some(None)
                } else {
                    minutes.map(Some)
                },
                assignee_id: if unassign {
                    Some(None)
                } else {
                    assign_to.map(Some)
                },
            };
            let updated = match if_version {
                Some(version) => store.edit_if_version(&id, version, patch)?,
                None => store.edit(&id, patch)?,
            };
            println!("Updated {} [revision {}]", updated.title, updated.version);
        }
        Command::Remove { id, if_version } => {
            if let Some(version) = if_version {
                store.delete_if_version(&id, version)?;
            } else {
                store.delete(&id)?;
            }
            println!("Task moved to tombstones");
        }
    }
    Ok(())
}
