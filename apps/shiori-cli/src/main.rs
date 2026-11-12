//! A small local-only client for exercising the same Rust domain and storage layers
//! that future desktop, Android, API and MCP adapters will call.
use chrono::{DateTime, FixedOffset, Local, NaiveDate, NaiveTime, Utc};
use clap::{Parser, Subcommand};
use shiori_core::scheduling::{Interval, PlanRequest, PlanningTask, UnscheduledReason, plan_day};
use shiori_core::{Priority, Task, TaskPatch, TaskStatus, validate_assignee_id, validate_estimate};
use shiori_storage::{SqliteStore, TaskFilter};
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
        due: Option<NaiveDate>,
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
        on: Option<NaiveDate>,
    },
    /// Preview one workday's time blocks without modifying tasks
    Plan {
        date: NaiveDate,
        #[arg(long, default_value = "08:00")]
        start: NaiveTime,
        #[arg(long, default_value = "17:00")]
        end: NaiveTime,
        #[arg(long, requires = "break_end")]
        break_start: Option<NaiveTime>,
        #[arg(long, requires = "break_start")]
        break_end: Option<NaiveTime>,
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
        due: Option<NaiveDate>,
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
            task.created_at.to_rfc3339(),
            task.updated_at.to_rfc3339(),
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
            task.created_at.to_rfc3339(),
            task.updated_at.to_rfc3339(),
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

fn main() -> Result<(), Box<dyn Error>> {
    let args = Args::parse();
    let path = match args.database {
        Some(path) => path,
        None => default_database()?,
    };
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
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
            let today = on.unwrap_or_else(|| Local::now().date_naive());
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
            let offset =
                FixedOffset::east_opt(seconds).ok_or("UTC offset minutes must fit within a day")?;
            let local_to_utc = |clock: NaiveTime| -> Result<DateTime<Utc>, Box<dyn Error>> {
                let local = date
                    .and_time(clock)
                    .and_local_timezone(offset)
                    .single()
                    .ok_or("ambiguous or invalid local time")?;
                Ok(local.with_timezone(&Utc))
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
                    block.start.with_timezone(&offset).format("%H:%M"),
                    block.end.with_timezone(&offset).format("%H:%M"),
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
        Command::BridgeDump => bridge_dump(&store.list(TaskFilter::default())?)?,
        Command::BridgeAttention => {
            bridge_attention(&store.assigned_attention("local")?)?;
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
