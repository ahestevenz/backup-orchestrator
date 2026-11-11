// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! The result file, written by `run` and read by `ctl result` (CLAUDE.md §5.4).

use serde::{Deserialize, Serialize};

use crate::job::{Job, JobKind, PROTOCOL_MAX};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum State {
    Running,
    Done,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Fda {
    Granted,
    Denied,
    NotApplicable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Ok,
    Failed,
}

/// Why a module failed (§5.10). `source_empty` is D-55.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorKind {
    Missing,
    DriveMissing,
    SourceEmpty,
    Permission,
    Tcc,
    ServerDenied,
    Network,
    Stalled,
    Timeout,
    Skipped,
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ModuleResult {
    pub name: String,
    pub status: Status,
    pub rsync_exit: Option<i32>,
    pub error_kind: Option<ErrorKind>,
    pub message: String,
    pub files_transferred: u64,
    pub bytes_transferred: u64,
    pub suspect_count: u64,
    pub suspect_files: Vec<String>,
}

impl ModuleResult {
    pub fn ok(name: &str) -> ModuleResult {
        ModuleResult {
            name: name.to_string(),
            status: Status::Ok,
            rsync_exit: None,
            error_kind: None,
            message: String::new(),
            files_transferred: 0,
            bytes_transferred: 0,
            suspect_count: 0,
            suspect_files: Vec::new(),
        }
    }

    pub fn failed(name: &str, kind: ErrorKind, message: impl Into<String>) -> ModuleResult {
        ModuleResult {
            status: Status::Failed,
            error_kind: Some(kind),
            message: message.into(),
            ..ModuleResult::ok(name)
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct JobResult {
    pub protocol: u32,
    pub job_id: String,
    pub run_id: String,
    pub kind: JobKind,
    pub user: String,
    pub agent_version: String,
    pub state: State,
    pub started_at: String,
    pub finished_at: Option<String>,
    pub fda: Fda,
    pub server_reachable: Option<bool>,
    pub server_error: Option<String>,
    pub server_error_kind: Option<String>,
    pub notes: Vec<String>,
    pub modules: Vec<ModuleResult>,
}

impl JobResult {
    pub fn start(job: &Job, started_at: String, fda: Fda) -> JobResult {
        JobResult {
            protocol: PROTOCOL_MAX.min(job.protocol),
            job_id: job.job_id.clone(),
            run_id: job.run_id.clone(),
            kind: job.kind,
            user: job.user.clone(),
            agent_version: env!("CARGO_PKG_VERSION").to_string(),
            state: State::Running,
            started_at,
            finished_at: None,
            fda,
            server_reachable: None,
            server_error: None,
            server_error_kind: None,
            notes: Vec::new(),
            modules: Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::job::tests::job;

    #[test]
    fn json_round_trip_and_names() {
        let mut r = JobResult::start(&job(), "2026-11-10T10:30:00Z".into(), Fda::NotApplicable);
        r.modules.push(ModuleResult::failed(
            "sofia-documents",
            ErrorKind::DriveMissing,
            "no drive",
        ));
        r.modules.push(ModuleResult::ok("sofia-athena"));
        let text = serde_json::to_string(&r).unwrap();
        assert!(text.contains("\"error_kind\":\"drive_missing\""));
        assert!(text.contains("\"fda\":\"not_applicable\""));
        assert!(text.contains("\"state\":\"running\""));
        assert!(text.contains("\"status\":\"failed\""));
        let back: JobResult = serde_json::from_str(&text).unwrap();
        assert_eq!(back, r);
    }

    #[test]
    fn unknown_result_fields_are_ignored() {
        let r = JobResult::start(&job(), "t".into(), Fda::Granted);
        let mut v = serde_json::to_value(&r).unwrap();
        v["future_field"] = serde_json::json!(1);
        let back: JobResult = serde_json::from_value(v).unwrap();
        assert_eq!(back, r);
    }
}
