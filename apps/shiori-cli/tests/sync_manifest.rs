//! Real Rust SQLite -> local-only identity manifest contract.
use std::{path::Path,process::{Command,Output}};
fn invoke(db:&Path,args:&[&str])->Output{
 Command::new(env!("CARGO_BIN_EXE_shiori-cli")).arg("--database").arg(db).args(args).output().unwrap()
}
fn created_id(out:Output)->String{
 assert!(out.status.success(),"{}",String::from_utf8_lossy(&out.stderr));
 let s=String::from_utf8(out.stdout).unwrap();
 s.trim().rsplit_once('[').unwrap().1.trim_end_matches(']').to_owned()
}
fn rows(raw:&[u8])->Vec<Vec<String>>{
 let prefix=b"SHIORI-MANIFEST-1\n";
 assert!(raw.starts_with(prefix));
 let mut pos=prefix.len();
 let mut rows=Vec::new();
 while pos<raw.len(){
  let mut row=Vec::new();
  for _ in 0..6{
   let end=pos+4;
   let n=u32::from_be_bytes(raw[pos..end].try_into().unwrap()) as usize;
   pos=end;
   row.push(String::from_utf8(raw[pos..pos+n].to_vec()).unwrap());
   pos+=n;
  }
  rows.push(row);
 }
 rows
}
#[test]
fn manifest_lists_versions_dependencies_and_tombstones_without_notes(){
 let dir=std::env::temp_dir().join(format!("shiori-manifest-test-{}-{}",std::process::id(),
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
 std::fs::create_dir_all(&dir).unwrap();
 let db=dir.join("tasks.sqlite3");
 let a=created_id(invoke(&db,&["add","Secret alpha task","--notes","DO NOT EXPORT CUSTOMER NOTE"]));
 let b=created_id(invoke(&db,&["add","Secret beta task"]));
 assert!(invoke(&db,&["depends",&b,"--on",&a]).status.success());
 let output=invoke(&db,&["bridge-manifest"]);
 assert!(output.status.success(),"{}",String::from_utf8_lossy(&output.stderr));
 let text=String::from_utf8_lossy(&output.stdout);
 assert!(!text.contains("Secret alpha task"));
 assert!(!text.contains("DO NOT EXPORT CUSTOMER NOTE"));
 let parsed=rows(&output.stdout);
 assert_eq!(parsed.len(),2);
 assert_eq!(parsed.iter().find(|x|x[0]==b).unwrap()[5],a);
 assert_eq!(parsed.iter().find(|x|x[0]==b).unwrap()[1],"2");
 assert!(invoke(&db,&["remove",&a,"--if-version","1"]).status.success());
 let after=invoke(&db,&["bridge-manifest"]);
 assert!(after.status.success());
 let parsed=rows(&after.stdout);
 assert_eq!(parsed.len(),2,"a tombstone must stay in the manifest");
 let removed=parsed.iter().find(|x|x[0]==a).unwrap();
 assert_eq!(removed[1],"2");
 assert!(!removed[4].is_empty(),"tombstone timestamp required");
 std::fs::remove_dir_all(dir).unwrap();
}
