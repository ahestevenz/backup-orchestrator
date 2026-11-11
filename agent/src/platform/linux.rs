// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

// Compiled on every OS (for tests); only used on linux.
#![cfg_attr(not(target_os = "linux"), allow(dead_code))]

//! Linux: the systemd template unit `bn-backup-agent@<user>` (CLAUDE.md §5.7).

use std::path::Path;

use super::{valid_mac, MacAddr};
use crate::paths::Layout;
use crate::util::{run_cmd, CtlError};

/// The unit file shipped in the .deb.
pub const UNIT_FILE: &str = include_str!("../../packaging/linux/bn-backup-agent@.service");

pub fn unit(user: &str) -> String {
    format!("bn-backup-agent@{user}.service")
}

/// The template unit serves every user, so there is nothing to install.
pub fn install_user_job(_layout: &Layout, _user: &str) -> Result<(), CtlError> {
    Ok(())
}

pub fn remove_user_job(user: &str) -> Result<(), CtlError> {
    stop(user)
}

pub fn is_running(user: &str) -> bool {
    let (_, out, _) = run_cmd("systemctl", &["is-active", &unit(user)]);
    matches!(out.trim(), "active" | "activating")
}

pub fn start(user: &str) -> Result<(), CtlError> {
    let (ok, _, err) = run_cmd("systemctl", &["start", "--no-block", &unit(user)]);
    if ok {
        Ok(())
    } else {
        Err(CtlError::new(
            "start_failed",
            format!("systemctl start: {}", err.trim()),
        ))
    }
}

pub fn stop(user: &str) -> Result<(), CtlError> {
    let _ = run_cmd("systemctl", &["stop", &unit(user)]);
    Ok(())
}

pub fn open_fda_settings() -> Result<serde_json::Value, CtlError> {
    Err(CtlError::new(
        "not_supported",
        "Full Disk Access exists only on macOS",
    ))
}

/// Interfaces from `/sys/class/net`. Wired: Ethernet type, a real device, not wireless.
pub fn mac_addresses_in(root: &Path) -> Vec<MacAddr> {
    let mut out = Vec::new();
    let Ok(rd) = std::fs::read_dir(root) else {
        return out;
    };
    let mut names: Vec<String> = rd
        .filter_map(|e| e.ok())
        .filter_map(|e| e.file_name().into_string().ok())
        .filter(|n| n != "lo")
        .collect();
    names.sort();
    for name in names {
        let dir = root.join(&name);
        let mac = std::fs::read_to_string(dir.join("address"))
            .unwrap_or_default()
            .trim()
            .to_lowercase();
        if !valid_mac(&mac) {
            continue;
        }
        let ty = std::fs::read_to_string(dir.join("type")).unwrap_or_default();
        let wired =
            ty.trim() == "1" && dir.join("device").exists() && !dir.join("wireless").exists();
        out.push(MacAddr {
            iface: name,
            mac,
            wired,
        });
    }
    out
}

pub fn mac_addresses() -> Vec<MacAddr> {
    mac_addresses_in(Path::new("/sys/class/net"))
}

pub fn uninstall_extras() -> Result<Option<String>, CtlError> {
    Ok(Some("run: sudo apt-get remove bn-backup-agent".into()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unit_file() {
        for line in [
            "Type=oneshot",
            "User=%i",
            "ExecStart=/usr/bin/bn-backup-agent run --user %i",
            "Nice=10",
            "IOSchedulingClass=best-effort",
            "TimeoutStartSec=infinity",
        ] {
            assert!(UNIT_FILE.lines().any(|l| l == line), "missing {line}");
        }
        assert!(!UNIT_FILE.contains("[Install]"));
        assert_eq!(unit("ariel"), "bn-backup-agent@ariel.service");
    }

    #[test]
    fn sys_class_net() {
        let d = tempfile::tempdir().unwrap();
        let mk = |name: &str, mac: &str, ty: &str, device: bool, wireless: bool| {
            let p = d.path().join(name);
            std::fs::create_dir_all(&p).unwrap();
            std::fs::write(p.join("address"), format!("{mac}\n")).unwrap();
            std::fs::write(p.join("type"), format!("{ty}\n")).unwrap();
            if device {
                std::fs::create_dir(p.join("device")).unwrap();
            }
            if wireless {
                std::fs::create_dir(p.join("wireless")).unwrap();
            }
        };
        mk("lo", "00:00:00:00:00:00", "772", false, false);
        mk("enp3s0", "AA:BB:CC:00:00:01", "1", true, false);
        mk("wlp2s0", "aa:bb:cc:00:00:02", "1", true, true);
        mk("docker0", "02:42:00:00:00:03", "1", false, false);
        let m = mac_addresses_in(d.path());
        assert_eq!(m.len(), 3);
        let wired: Vec<&str> = m
            .iter()
            .filter(|x| x.wired)
            .map(|x| x.iface.as_str())
            .collect();
        assert_eq!(wired, ["enp3s0"]);
        assert_eq!(
            m.iter().find(|x| x.iface == "enp3s0").unwrap().mac,
            "aa:bb:cc:00:00:01"
        );
    }
}
