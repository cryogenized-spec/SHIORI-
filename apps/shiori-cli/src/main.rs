//! A small local-only client for exercising the same Rust domain and storage layers
//! that future desktop, Android, API and MCP adapters will call.
use chrono::NaiveDate;
use clap::{Parser, Subcommand};
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
