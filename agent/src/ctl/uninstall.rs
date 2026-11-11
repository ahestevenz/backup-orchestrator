// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl uninstall`: remove everything the agent installed. Run by the operator
//! with their password, never through the control key (CLAUDE.md §5.2).

use serde_json::json;

use super::setup::{update_admin_authorized_keys, without_control_key};
use super::Output;
use crate::paths::{Layout, Os};
use crate::platform::current;
use crate::util::CtlError;

pub fn run(layout: &Layout, _os: Os) -> Result<Output, CtlError> {
    let admin = layout.load_config().ok().map(|c| c.admin_user);
    for user in layout.users() {
        if current::is_running(&user) {
            current::stop(&user)?;
        }
        current::remove_user_job(&user)?;
    }
    if layout.home.exists() {
        std::fs::remove_dir_all(&layout.home)?;
    }
    crate::sudoers::remove();
    if let Some(admin) = admin {
        update_admin_authorized_keys(&admin, without_control_key)?;
    }
    let note = current::uninstall_extras()?;
    Ok(Output::Json(match note {
        Some(n) => json!({"ok": true, "note": n}),
        None => json!({"ok": true}),
    }))
}
