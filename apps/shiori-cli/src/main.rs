//! A small local-only client for exercising the same Rust domain and storage layers
//! that future desktop, Android, API and MCP adapters will call.
use chrono::{DateTime, FixedOffset, Local, NaiveDate, NaiveTime, Utc};
use clap::{Parser, Subcommand};
use shiori_core::scheduling::{
    Interval, PlanRequest, PlanningTask, UnscheduledReason, plan_day,
};
use shiori_core::{Priority, Task, TaskPatch, TaskStatus};
use shiori_storage::{SqliteStore, TaskFilter};
use std::{error::Error, path::PathBuf};

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
        /// Estimate applied to every task until duration is stored on tasks.
        #[arg(long, default_value_t = 30)]
        default_minutes: i64,
    },
    /// View one task by its ID
    Show { id: String },
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
        /// Reject if the task changed since this revision was read
        #[arg(long)]
        if_version: Option<i64>,
    },
    /// Soft-delete a task (retains a tombstone)
    Remove { id: String },
}

fn default_database() -> Result<PathBuf, Box<dyn Error>> {
    if let Some(base) = std::env::var_os("XDG_DATA_HOME") {
        return Ok(PathBuf::from(base).join("shiori/tasks.sqlite3"));
    }
    let home =
        std::env::var_os("HOME").ok_or("HOME or XDG_DATA_HOME must be set, or pass --database")?;
    Ok(PathBuf::from(home).join(".local/share/shiori/tasks.sqlite3"))
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
    let store = SqliteStore::open(path)?;
    match args.command {
        Command::Add {
            title,
            project,
            priority,
            due,
        } => {
            let task = Task::new(&title, &project, priority, due)?;
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
            let offset = FixedOffset::east_opt(seconds)
                .ok_or("UTC offset minutes must fit within a day")?;
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
            let pending: Vec<PlanningTask> = store
                .list(TaskFilter::default())?
                .into_iter()
                .filter(|task| task.status != TaskStatus::Done)
                .map(|task| PlanningTask {
                    id: task.id,
                    title: task.title,
                    priority: task.priority,
                    due_on: task.due_on,
                    minutes: default_minutes,
                    dependencies: Vec::new(),
                })
                .collect();
            let result = plan_day(PlanRequest {
                day: date,
                tasks: pending,
                completed_ids: Vec::new(),
                availability,
                busy,
            })?;
            println!("PREVIEW ONLY · {date} · fixed UTC offset {utc_offset_minutes} minutes");
            println!("Each task uses a {default_minutes}-minute placeholder estimate.");
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
        Command::Show { id } => println!("{:#?}", store.get(&id)?),
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
            if_version,
        } => {
            let patch = TaskPatch {
                title,
                notes,
                project,
                priority,
                due_on: if clear_due { Some(None) } else { due.map(Some) },
            };
            let updated = match if_version {
                Some(version) => store.edit_if_version(&id, version, patch)?,
                None => store.edit(&id, patch)?,
            };
            println!("Updated {} [revision {}]", updated.title, updated.version);
        }
        Command::Remove { id } => {
            store.delete(&id)?;
            println!("Task moved to tombstones");
        }
    }
    Ok(())
}
