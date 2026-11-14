#![no_main]
use libfuzzer_sys::fuzz_target;
use shiori_core::{validate_title, TaskError};

fuzz_target!(|data: &[u8]| {
    if let Ok(s) = std::str::from_utf8(data) {
        let trimmed = s.trim();
        match validate_title(s) {
            Ok(validated) => {
                assert!(!validated.is_empty());
                assert_eq!(validated, trimmed);
                assert!(validated.chars().count() <= 160);
            }
            Err(TaskError::EmptyTitle) => assert!(trimmed.is_empty()),
            Err(TaskError::TitleTooLong) => assert!(trimmed.chars().count() > 160),
            Err(other) => panic!("unexpected title validation error: {other:?}"),
        }
    }
});
