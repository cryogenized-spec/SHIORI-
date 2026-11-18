//! CLI staging is explicitly local and never sends customer task text to stdout.
use std::{path::Path, process::{Command, Output}};
use tempfile::tempdir;

fn cli(db:&Path,args:&[&str])->Output {
    Command::new(env!("CARGO_BIN_EXE_shiori-cli")).arg("--database").arg(db).args(args).output().unwrap()
}
fn stdout(output:&Output)->String {
    assert!(output.status.success(),"{}",String::from_utf8_lossy(&output.stderr));
    String::from_utf8(output.stdout.clone()).unwrap()
}
#[test]
fn stages_one_revision_without_creating_a_remote_connection() {
    let folder=tempdir().unwrap();
    let db=folder.path().join("tasks.sqlite3");
    let created=stdout(&cli(&db,&["add","Secret project task","--notes","Customer private number"]));
    let id=created.rsplit_once('[').unwrap().1.trim_end_matches(']').trim();
    let stale=cli(&db,&["sync-stage",id,"--if-version","99"]);
    assert!(!stale.status.success(),"stale version must fail");
    assert!(!folder.path().join("tasks.sync.sqlite3").exists(),"no journal on stale preflight");

    let staged=stdout(&cli(&db,&["sync-stage",id,"--if-version","1"]));
    assert!(staged.contains("No network request or upload"));
    assert!(!staged.contains("Customer private number"));
    let queue=stdout(&cli(&db,&["sync-queue"]));
    assert!(queue.contains("1 queue entries"));
    assert!(queue.contains("pending"));
    assert!(!queue.contains("Secret project task"));
    assert!(!queue.contains("Customer private number"));
    let replay=stdout(&cli(&db,&["sync-stage",id,"--if-version","1"]));
    assert!(replay.contains("Already staged"));
    let queue=stdout(&cli(&db,&["sync-queue"]));
    assert!(queue.contains("1 queue entries"));
}
