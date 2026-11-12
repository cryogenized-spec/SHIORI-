//! End-to-end local CLI test: saved task durations and edges feed the planner.
use std::{path::Path, process::{Command, Output}};

fn invoke(database: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_shiori-cli"))
        .arg("--database")
        .arg(database)
        .args(args)
        .output()
        .unwrap()
}

fn created_id(output: Output) -> String {
    assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
    let out = String::from_utf8(output.stdout).unwrap();
    out.trim()
        .rsplit_once('[')
        .unwrap()
        .1
        .trim_end_matches(']')
        .to_owned()
}

#[test]
fn stored_effort_and_prerequisites_drive_real_cli_preview() {
    let temp = tempfile::tempdir().unwrap();
    let db = temp.path().join("tasks.sqlite3");
    let prepare = created_id(invoke(
        &db,
        &["add", "Prepare", "--minutes", "45", "--priority", "low"],
    ));
    let publish = created_id(invoke(
        &db,
        &["add", "Publish", "--minutes", "30", "--priority", "urgent"],
    ));
    let deps = invoke(&db, &["depends", &publish, "--on", &prepare]);
    assert!(deps.status.success(), "{}", String::from_utf8_lossy(&deps.stderr));
    let rejected = invoke(&db, &["depends", &prepare, "--on", &publish]);
    assert!(!rejected.status.success(), "cycle must fail");
    let preview = invoke(
        &db,
        &[
            "plan", "2026-11-12", "--start", "08:00", "--end", "09:30",
            "--utc-offset-minutes", "120", "--default-minutes", "90",
        ],
    );
    assert!(preview.status.success(), "{}", String::from_utf8_lossy(&preview.stderr));
    let text = String::from_utf8(preview.stdout).unwrap();
    assert!(text.contains("08:00–08:45  Prepare"), "{text}");
    assert!(text.contains("08:45–09:15  Publish"), "{text}");
    let shown = invoke(&db, &["show", &publish]);
    assert!(shown.status.success());
    let shown_text = String::from_utf8(shown.stdout).unwrap();
    assert!(shown_text.contains("estimate_minutes: Some(30)"));
    assert!(shown_text.contains(&prepare));
}
