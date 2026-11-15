//! Visual-only coordinates for SHIORI's Infinite Spatial Workspace.
//! Positions never express or mutate task dependencies or domain status.
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const MAX_COORDINATE: f64 = 1_000_000.0;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SpatialPosition {
    pub task_id: String,
    pub x: f64,
    pub y: f64,
    /// Separate view revision: never increment a canonical task revision
    /// just because a user rearranged cards on a canvas.
    pub revision: i64,
}

#[derive(Debug, Error, PartialEq)]
pub enum SpatialError {
    #[error("canvas coordinates must be finite and within +/- 1,000,000")]
    InvalidCoordinate,
    #[error("invalid visual revision")]
    InvalidRevision,
}

pub fn validate_coordinates(x: f64, y: f64) -> Result<(), SpatialError> {
    if !x.is_finite() || !y.is_finite() || x.abs() > MAX_COORDINATE || y.abs() > MAX_COORDINATE {
        return Err(SpatialError::InvalidCoordinate);
    }
    Ok(())
}
pub fn validate_view_revision(version: i64) -> Result<(), SpatialError> {
    if version < 0 {
        return Err(SpatialError::InvalidRevision);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_nonfinite_and_out_of_bounds() {
        assert_eq!(validate_coordinates(f64::NAN, 0.0), Err(SpatialError::InvalidCoordinate));
        assert_eq!(validate_coordinates(1e12, 0.0), Err(SpatialError::InvalidCoordinate));
        assert_eq!(validate_coordinates(0.0, f64::INFINITY), Err(SpatialError::InvalidCoordinate));
        assert!(validate_coordinates(-1e6, 1e6).is_ok());
    }
    #[test]
    fn view_revision_independent_and_nonnegative() {
        assert!(validate_view_revision(0).is_ok());
        assert!(validate_view_revision(2).is_ok());
        assert_eq!(validate_view_revision(-1), Err(SpatialError::InvalidRevision));
    }
}
