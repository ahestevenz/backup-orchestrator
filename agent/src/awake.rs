// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! Keep the computer awake while a job runs (CLAUDE.md §5.3 step 2).

use std::process::{Child, Command, Stdio};

use crate::paths::Os;

/// Holds `caffeinate` (macOS) or `systemd-inhibit` (Linux) until dropped.
pub struct KeepAwake {
    child: Option<Child>,
}

impl KeepAwake {
    pub fn start(os: Os, notes: &mut Vec<String>) -> KeepAwake {
        let pid = std::process::id().to_string();
        let mut cmd = match os {
            Os::MacOs => {
                let mut c = Command::new("/usr/bin/caffeinate");
                c.args(["-i", "-s", "-w", &pid]);
                c
            }
            Os::Linux => {
                let mut c = Command::new("systemd-inhibit");
                c.args([
                    "--what=sleep:idle",
                    "--who=bn-backup-agent",
                    "--why=backup running",
                    "--mode=block",
                    "sleep",
                    "infinity",
                ]);
                c
            }
        };
        let child = cmd
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
        match child {
            Ok(c) => KeepAwake { child: Some(c) },
            Err(e) => {
                notes.push(format!("could not keep the computer awake: {e}"));
                KeepAwake { child: None }
            }
        }
    }
}

impl Drop for KeepAwake {
    fn drop(&mut self) {
        if let Some(c) = self.child.as_mut() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }
}
