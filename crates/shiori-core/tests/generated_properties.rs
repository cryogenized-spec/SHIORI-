//! Reproducible, dependency-free generative checks for core invariants.
//! Each failure includes its case index. The seed is intentionally fixed for CI.
use shiori_core::{Priority, Task, TaskError, TaskStatus, validate_title};
use std::str::FromStr;

fn next(state: &mut u64) -> u64 {
    *state ^= *state << 13;
    *state ^= *state >> 7;
    *state ^= *state << 17;
    *state
}

#[test]
fn generated_unicode_titles_follow_the_documented_rules() {
    let mut seed = 0x5A10_2026_ABCD_1234_u64;
    let alphabet = ['a', 'Z', '栞', '字', '😀', ' ', '\t', '\n', '%', '_', '\\'];
    for case in 0..2_000 {
        let len = (next(&mut seed) % 180) as usize;
        let value: String = (0..len)
            .map(|_| alphabet[(next(&mut seed) as usize) % alphabet.len()])
            .collect();
        let trimmed = value.trim();
        let expected = if trimmed.is_empty() {
            Err(TaskError::EmptyTitle)
        } else if trimmed.chars().count() > 160 {
            Err(TaskError::TitleTooLong)
        } else {
            Ok(trimmed.to_owned())
        };
        assert_eq!(validate_title(&value), expected, "seeded title case {case}");
    }
}

#[test]
fn invalid_renames_are_atomic_and_do_not_increment_version() {
    let mut task = Task::new("Original", "Inbox", Priority::Medium, None).unwrap();
    for invalid in ["   ", "\n\t", &"x".repeat(161)] {
        let title = task.title.clone();
        let revision = task.version;
        assert!(task.rename(invalid).is_err());
        assert_eq!(task.title, title);
        assert_eq!(task.version, revision);
    }
}

#[test]
fn generated_status_transitions_keep_completion_and_versions_consistent() {
    let mut seed = 0xABCD_EF01_1100_2026_u64;
    let mut task = Task::new("Transition", "Inbox", Priority::Low, None).unwrap();
    for step in 0..1_000 {
        let status = match next(&mut seed) % 3 {
            0 => TaskStatus::Todo,
            1 => TaskStatus::InProgress,
            _ => TaskStatus::Done,
        };
        let before = task.version;
        task.change_status(status);
        assert_eq!(task.version, before + 1, "step {step}");
        assert_eq!(
            task.completed_at.is_some(),
            status == TaskStatus::Done,
            "step {step}"
        );
    }
}

#[test]
fn persisted_enum_strings_round_trip_or_reject_unknown_values() {
    for priority in [
        Priority::Low,
        Priority::Medium,
        Priority::High,
        Priority::Urgent,
    ] {
        assert_eq!(Priority::from_str(priority.as_str()).unwrap(), priority);
    }
    for status in [TaskStatus::Todo, TaskStatus::InProgress, TaskStatus::Done] {
        assert_eq!(TaskStatus::from_str(status.as_str()).unwrap(), status);
    }
    assert!(Priority::from_str("emergency").is_err());
    assert!(TaskStatus::from_str("archived").is_err());
}
