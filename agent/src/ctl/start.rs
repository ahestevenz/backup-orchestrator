// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl start <user>`: launchctl kickstart or systemctl start (D-05).

use super::{check_user, ok, Output};
use crate::paths::Layout;
use crate::platform::current;
use crate::util::CtlError;

pub fn run(layout: &Layout, user: &str) -> Result<Output, CtlError> {
    check_user(user)?;
    if !layout.job_json(user).exists() {
        return Err(CtlError::new(
            "no_job",
            format!("no job has been submitted for {user}"),
        ));
    }
    if current::is_running(user) {
        return Err(CtlError::new(
            "busy",
            format!("a job for {user} is already running"),
        ));
    }
    current::start(user)?;
    Ok(ok())
}
