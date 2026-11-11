// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! The job file, written by the server through `ctl submit` (CLAUDE.md §5.4).

use serde::{Deserialize, Serialize};

use crate::paths::AgentConfig;
use crate::util::{valid_module_name, valid_user_name, CtlError};

pub const PROTOCOL_MIN: u32 = 1;
pub const PROTOCOL_MAX: u32 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum JobKind {
    Backup,
    Probe,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ModuleType {
    #[serde(rename = "path")]
    Path,
    #[serde(rename = "host-config")]
    HostConfig,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ServerRef {
    pub host: String,
    pub port: u16,
    pub user: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Options {
    pub verify: bool,
    pub partial: bool,
    pub dry_run: bool,
    pub io_timeout_seconds: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModuleJob {
    pub name: String,
    #[serde(rename = "type")]
    pub kind: ModuleType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub src_path: Option<String>,
    #[serde(default)]
    pub excludes: Vec<String>,
    /// D-55: the module's backup already holds data, so an empty source is an error.
    #[serde(default)]
    pub expect_nonempty: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Job {
    pub protocol: u32,
    pub kind: JobKind,
    pub job_id: String,
    pub run_id: String,
    pub user: String,
    pub host_name: String,
    pub server: ServerRef,
    pub options: Options,
    pub timeout_seconds: u64,
    pub modules: Vec<ModuleJob>,
}

impl Job {
    pub fn parse(bytes: &[u8]) -> Result<Job, CtlError> {
        serde_json::from_slice(bytes)
            .map_err(|e| CtlError::new("bad_job", format!("the job is not valid: {e}")))
    }

    /// Checks done by `ctl submit` before the job is accepted (§5.2).
    pub fn validate(&self, user: &str, cfg: &AgentConfig) -> Result<(), CtlError> {
        let bad = |m: String| Err(CtlError::new("bad_job", m));
        if !(PROTOCOL_MIN..=PROTOCOL_MAX).contains(&self.protocol) {
            return Err(CtlError::new(
                "protocol",
                format!(
                    "job protocol {} is not supported (this agent: {PROTOCOL_MIN}..{PROTOCOL_MAX})",
                    self.protocol
                ),
            ));
        }
        if self.user != user {
            return bad(format!("job is for {:?}, not {user:?}", self.user));
        }
        if !valid_user_name(&self.user) {
            return bad(format!("invalid user name {:?}", self.user));
        }
        if self.server.host != cfg.server_host
            || self.server.port != cfg.server_port
            || self.server.user != cfg.server_user
            || self.host_name != cfg.host_name
        {
            return Err(CtlError::new(
                "server_mismatch",
                "the job names a different server or host than this agent was set up for",
            ));
        }
        if self.job_id.is_empty() || self.job_id.len() > 64 {
            return bad("job_id must be 1 to 64 characters".into());
        }
        if self.options.io_timeout_seconds == 0 {
            return bad("io_timeout_seconds must be positive".into());
        }
        let mut seen = std::collections::HashSet::new();
        for m in &self.modules {
            if !valid_module_name(&m.name) {
                return bad(format!("invalid module name {:?}", m.name));
            }
            if !seen.insert(m.name.as_str()) {
                return bad(format!("module {:?} is listed twice", m.name));
            }
            match (m.kind, &m.src_path) {
                (ModuleType::Path, Some(p)) => {
                    if !p.starts_with('/') || p == "/" || p.ends_with('/') {
                        return bad(format!(
                            "module {:?}: src_path must be absolute, not / and without a trailing /",
                            m.name
                        ));
                    }
                }
                (ModuleType::Path, None) => {
                    return bad(format!("module {:?}: src_path is missing", m.name))
                }
                (ModuleType::HostConfig, Some(_)) => {
                    return bad(format!(
                        "module {:?}: host-config takes no src_path",
                        m.name
                    ))
                }
                (ModuleType::HostConfig, None) => {}
            }
            if m.excludes.iter().any(|e| e.is_empty() || e.contains('\n')) {
                return bad(format!("module {:?}: invalid exclude pattern", m.name));
            }
        }
        if self.kind == JobKind::Backup && self.modules.is_empty() {
            return bad("a backup job needs at least one module".into());
        }
        Ok(())
    }
}

#[cfg(test)]
pub mod tests {
    use super::*;

    pub fn cfg() -> AgentConfig {
        AgentConfig {
            server_host: "server.home.lan".into(),
            server_port: 22,
            server_user: "ariel".into(),
            admin_user: "ariel".into(),
            host_name: "athena".into(),
        }
    }

    pub const JOB: &str = r#"{
      "protocol": 1, "kind": "backup", "job_id": "3f0c", "run_id": "20261110-213000",
      "user": "sofia", "host_name": "athena",
      "server": {"host": "server.home.lan", "port": 22, "user": "ariel"},
      "options": {"verify": false, "partial": true, "dry_run": false, "io_timeout_seconds": 600},
      "timeout_seconds": 0,
      "modules": [
        {"name": "sofia-documents", "type": "path", "src_path": "/Users/sofia/Documents",
         "excludes": [".DS_Store"], "expect_nonempty": true},
        {"name": "sofia-athena", "type": "host-config"}
      ]
    }"#;

    pub fn job() -> Job {
        Job::parse(JOB.as_bytes()).unwrap()
    }

    #[test]
    fn parses_the_documented_example() {
        let j = job();
        assert_eq!(j.kind, JobKind::Backup);
        assert_eq!(j.modules[1].kind, ModuleType::HostConfig);
        assert!(j.modules[0].expect_nonempty);
        j.validate("sofia", &cfg()).unwrap();
    }

    #[test]
    fn unknown_fields_are_rejected() {
        let text = JOB.replace(
            "\"timeout_seconds\": 0,",
            "\"timeout_seconds\": 0, \"x\": 1,",
        );
        assert_eq!(Job::parse(text.as_bytes()).unwrap_err().code, "bad_job");
    }

    #[test]
    fn wrong_user_protocol_server() {
        assert_eq!(job().validate("ariel", &cfg()).unwrap_err().code, "bad_job");
        let mut j = job();
        j.protocol = 2;
        assert_eq!(j.validate("sofia", &cfg()).unwrap_err().code, "protocol");
        let mut j = job();
        j.server.host = "evil.example.com".into();
        assert_eq!(
            j.validate("sofia", &cfg()).unwrap_err().code,
            "server_mismatch"
        );
        let mut j = job();
        j.host_name = "galactica".into();
        assert_eq!(
            j.validate("sofia", &cfg()).unwrap_err().code,
            "server_mismatch"
        );
    }

    #[test]
    fn module_rules() {
        type Change = Box<dyn Fn(&mut Job)>;
        let cases: Vec<Change> = vec![
            Box::new(|j| j.modules[0].src_path = Some("relative".into())),
            Box::new(|j| j.modules[0].src_path = Some("/Users/sofia/".into())),
            Box::new(|j| j.modules[0].src_path = Some("/".into())),
            Box::new(|j| j.modules[0].src_path = None),
            Box::new(|j| j.modules[0].name = "../x".into()),
            Box::new(|j| j.modules[1].src_path = Some("/etc".into())),
            Box::new(|j| j.modules[1].name = "sofia-documents".into()),
        ];
        for change in cases {
            let mut j = job();
            change(&mut j);
            assert_eq!(j.validate("sofia", &cfg()).unwrap_err().code, "bad_job");
        }
    }
}
