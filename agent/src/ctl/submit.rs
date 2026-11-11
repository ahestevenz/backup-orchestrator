// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl submit <user>`: accept a job from the server (CLAUDE.md §5.2).
//! Only root writes job.json, so a user cannot change their own job.

use std::io::Read;

use nix::unistd::{Gid, Uid};
use serde_json::json;

use super::{check_user, Output};
use crate::job::Job;
use crate::paths::Layout;
use crate::platform::current;
use crate::util::{atomic_write, read_capped, CtlError};

pub const MAX_JOB_BYTES: usize = 1024 * 1024;

/// Read and validate a job. Separate from `run` so it can be tested without root.
pub fn accept(layout: &Layout, user: &str, stdin: &mut dyn Read) -> Result<Job, CtlError> {
    check_user(user)?;
    let cfg = layout.load_config()?;
    if !layout.key(user).exists() {
        return Err(CtlError::new(
            "user_not_set_up",
            format!("{user} is not set up on this host; run bn-backup hosts configure"),
        ));
    }
    let bytes = read_capped(stdin, MAX_JOB_BYTES)?;
    let job = Job::parse(&bytes)?;
    job.validate(user, &cfg)?;
    Ok(job)
}

pub fn run(layout: &Layout, user: &str, stdin: &mut dyn Read) -> Result<Output, CtlError> {
    let job = accept(layout, user, stdin)?;
    if current::is_running(user) {
        return Err(CtlError::new(
            "busy",
            format!("a job for {user} is still running"),
        ));
    }
    let text = serde_json::to_vec_pretty(&job).map_err(|e| CtlError::internal(e.to_string()))?;
    let root = Some((Uid::from_raw(0), Gid::from_raw(0)));
    atomic_write(&layout.job_json(user), &text, 0o644, root)?;
    match std::fs::remove_file(layout.result_json(user)) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.into()),
    }
    Ok(Output::Json(json!({"ok": true, "job_id": job.job_id})))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::job::tests::{cfg, JOB};

    fn layout() -> (tempfile::TempDir, Layout) {
        let d = tempfile::tempdir().unwrap();
        let l = Layout {
            home: d.path().into(),
        };
        std::fs::write(l.agent_toml(), cfg().to_toml()).unwrap();
        std::fs::create_dir_all(l.state_dir("sofia")).unwrap();
        std::fs::write(l.key("sofia"), "k").unwrap();
        (d, l)
    }

    #[test]
    fn accepts_a_valid_job() {
        let (_d, l) = layout();
        let job = accept(&l, "sofia", &mut JOB.as_bytes()).unwrap();
        assert_eq!(job.job_id, "3f0c");
    }

    #[test]
    fn refuses_bad_input() {
        let (_d, l) = layout();
        assert_eq!(
            accept(&l, "sofia", &mut &b"not json"[..]).unwrap_err().code,
            "bad_job"
        );
        assert_eq!(
            accept(&l, "ariel", &mut JOB.as_bytes()).unwrap_err().code,
            "user_not_set_up"
        );
        let big = vec![b' '; MAX_JOB_BYTES + 1];
        assert_eq!(
            accept(&l, "sofia", &mut &big[..]).unwrap_err().code,
            "bad_job"
        );
        let evil = JOB.replace("server.home.lan", "evil.example.com");
        assert_eq!(
            accept(&l, "sofia", &mut evil.as_bytes()).unwrap_err().code,
            "server_mismatch"
        );
    }

    #[test]
    fn needs_setup() {
        let d = tempfile::tempdir().unwrap();
        let l = Layout {
            home: d.path().into(),
        };
        assert_eq!(
            accept(&l, "sofia", &mut JOB.as_bytes()).unwrap_err().code,
            "not_configured"
        );
    }
}
