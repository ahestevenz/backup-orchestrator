// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! The sudoers drop-in: passwordless `ctl` for the admin account, nothing else
//! (CLAUDE.md §5.6, D-09).

use std::path::Path;

use nix::unistd::{Gid, Uid};

use crate::paths::SUDOERS_FILE;
use crate::util::{atomic_write, run_cmd, CtlError};

pub fn render(admin_user: &str, executable: &str) -> String {
    format!("{admin_user} ALL=(root) NOPASSWD: {executable} ctl *\n")
}

/// Validate with `visudo -cf` before installing it as 0440 root.
pub fn install(admin_user: &str, executable: &str) -> Result<(), CtlError> {
    let text = render(admin_user, executable);
    let target = Path::new(SUDOERS_FILE);
    let dir = target.parent().expect("sudoers.d");
    // A name with a dot: sudo ignores it while it is being checked.
    let tmp = dir.join(".bn-backup-agent.check");
    let root = Some((Uid::from_raw(0), Gid::from_raw(0)));
    atomic_write(&tmp, text.as_bytes(), 0o440, root)?;
    let (ok, out, err) = run_cmd("visudo", &["-cf", &tmp.to_string_lossy()]);
    if !ok {
        let _ = std::fs::remove_file(&tmp);
        return Err(CtlError::new(
            "sudoers_invalid",
            format!("visudo rejected the rule: {}{}", out.trim(), err.trim()),
        ));
    }
    std::fs::rename(&tmp, target)?;
    Ok(())
}

pub fn remove() {
    let _ = std::fs::remove_file(SUDOERS_FILE);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn one_line() {
        assert_eq!(
            render("ariel", "/usr/bin/bn-backup-agent"),
            "ariel ALL=(root) NOPASSWD: /usr/bin/bn-backup-agent ctl *\n"
        );
    }
}
