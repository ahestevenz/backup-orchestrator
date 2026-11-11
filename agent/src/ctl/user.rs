// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl user-add` and `ctl user-remove` (CLAUDE.md §5.2).

use std::os::unix::fs::PermissionsExt;

use nix::unistd::{chown, Gid, Uid, User};
use serde_json::json;

use super::{check_user, ok, Output};
use crate::paths::Layout;
use crate::platform::current;
use crate::util::{ensure_dir, run_cmd, CtlError};

fn root() -> Option<(Uid, Gid)> {
    Some((Uid::from_raw(0), Gid::from_raw(0)))
}

pub fn add(layout: &Layout, user: &str) -> Result<Output, CtlError> {
    check_user(user)?;
    let pw = User::from_name(user).ok().flatten().ok_or_else(|| {
        CtlError::new(
            "no_such_user",
            format!("there is no account {user:?} on this host"),
        )
    })?;
    let cfg = layout.load_config()?;
    ensure_dir(&layout.users_dir(), 0o755, root())?;
    ensure_dir(&layout.user_dir(user), 0o755, root())?;
    ensure_dir(&layout.state_dir(user), 0o700, Some((pw.uid, pw.gid)))?;

    let key = layout.key(user);
    if !key.exists() {
        let comment = format!("bn-backup-agent {user}@{}", cfg.host_name);
        let (ok, _, err) = run_cmd(
            "ssh-keygen",
            &[
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                &comment,
                "-f",
                &key.to_string_lossy(),
            ],
        );
        if !ok {
            return Err(CtlError::new(
                "keygen_failed",
                format!("ssh-keygen: {}", err.trim()),
            ));
        }
    }
    let public = layout.key_pub(user);
    for (path, mode) in [(&key, 0o600), (&public, 0o644)] {
        chown(path.as_path(), Some(pw.uid), Some(pw.gid)).map_err(std::io::Error::from)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    }
    current::install_user_job(layout, user)?;
    let public_key = std::fs::read_to_string(&public)?.trim().to_string();
    Ok(Output::Json(json!({"ok": true, "public_key": public_key})))
}

pub fn remove(layout: &Layout, user: &str) -> Result<Output, CtlError> {
    check_user(user)?;
    if current::is_running(user) {
        current::stop(user)?;
    }
    current::remove_user_job(user)?;
    let dir = layout.user_dir(user);
    if dir.exists() {
        std::fs::remove_dir_all(dir)?;
    }
    Ok(ok())
}
