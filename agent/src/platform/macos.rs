// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

// Compiled on every OS (for tests); only used on macos.
#![cfg_attr(not(target_os = "macos"), allow(dead_code))]

//! macOS: one LaunchDaemon per user, with `UserName` (CLAUDE.md §5.7).

use std::path::{Path, PathBuf};

use nix::unistd::{Gid, Uid};

use super::{valid_mac, MacAddr};
use crate::paths::{Layout, LABEL_PREFIX, MACOS_EXECUTABLE};
use crate::util::{atomic_write, run_cmd, CtlError};

pub fn label(user: &str) -> String {
    format!("{LABEL_PREFIX}.{user}")
}

pub fn plist_path(user: &str) -> PathBuf {
    PathBuf::from(format!("/Library/LaunchDaemons/{}.plist", label(user)))
}

fn xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// The per-user LaunchDaemon: runs `run --user <user>` as that user, only when started.
pub fn render_plist(user: &str, executable: &str, log: &Path) -> String {
    let log = xml(&log.to_string_lossy());
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{exe}</string>
    <string>run</string>
    <string>--user</string>
    <string>{user}</string>
  </array>
  <key>UserName</key>
  <string>{user}</string>
  <key>RunAtLoad</key>
  <false/>
  <key>ProcessType</key>
  <string>Standard</string>
  <key>StandardOutPath</key>
  <string>{log}</string>
  <key>StandardErrorPath</key>
  <string>{log}</string>
</dict>
</plist>
"#,
        label = xml(&label(user)),
        exe = xml(executable),
        user = xml(user),
    )
}

pub fn install_user_job(layout: &Layout, user: &str) -> Result<(), CtlError> {
    let plist = plist_path(user);
    let text = render_plist(user, MACOS_EXECUTABLE, &layout.agent_log(user));
    atomic_write(
        &plist,
        text.as_bytes(),
        0o644,
        Some((Uid::from_raw(0), Gid::from_raw(0))),
    )?;
    let target = format!("system/{}", label(user));
    let _ = run_cmd("/bin/launchctl", &["bootout", &target]);
    let (ok, _, err) = run_cmd(
        "/bin/launchctl",
        &["bootstrap", "system", &plist.to_string_lossy()],
    );
    if !ok {
        return Err(CtlError::new(
            "job_install_failed",
            format!("launchctl bootstrap: {}", err.trim()),
        ));
    }
    Ok(())
}

pub fn remove_user_job(user: &str) -> Result<(), CtlError> {
    let _ = run_cmd(
        "/bin/launchctl",
        &["bootout", &format!("system/{}", label(user))],
    );
    let plist = plist_path(user);
    if plist.exists() {
        std::fs::remove_file(plist)?;
    }
    Ok(())
}

/// `launchctl print` reports `state = running` while the job runs.
pub fn parse_state(print_output: &str) -> Option<String> {
    print_output
        .lines()
        .map(str::trim)
        .find_map(|l| l.strip_prefix("state = ").map(|s| s.trim().to_string()))
}

pub fn is_running(user: &str) -> bool {
    let (ok, out, _) = run_cmd(
        "/bin/launchctl",
        &["print", &format!("system/{}", label(user))],
    );
    ok && parse_state(&out).as_deref() == Some("running")
}

pub fn start(user: &str) -> Result<(), CtlError> {
    let (ok, _, err) = run_cmd(
        "/bin/launchctl",
        &["kickstart", &format!("system/{}", label(user))],
    );
    if ok {
        Ok(())
    } else {
        Err(CtlError::new(
            "start_failed",
            format!("launchctl kickstart: {}", err.trim()),
        ))
    }
}

pub fn stop(user: &str) -> Result<(), CtlError> {
    let _ = run_cmd(
        "/bin/launchctl",
        &["kill", "SIGTERM", &format!("system/{}", label(user))],
    );
    Ok(())
}

/// The user logged in at the screen, if any (`root` means the login window).
pub fn console_user() -> Option<(String, u32)> {
    use std::os::unix::fs::MetadataExt;
    let uid = std::fs::metadata("/dev/console").ok()?.uid();
    let name = nix::unistd::User::from_uid(Uid::from_raw(uid)).ok()??.name;
    Some((name, uid))
}

pub fn open_fda_settings() -> Result<serde_json::Value, CtlError> {
    let Some((user, uid)) = console_user() else {
        return Ok(serde_json::json!({"opened": false, "console_user": ""}));
    };
    if user == "root" || user == "loginwindow" {
        return Ok(serde_json::json!({"opened": false, "console_user": user}));
    }
    let (ok, _, _) = run_cmd(
        "/bin/launchctl",
        &[
            "asuser",
            &uid.to_string(),
            "/usr/bin/sudo",
            "-u",
            &user,
            "/usr/bin/open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
        ],
    );
    Ok(serde_json::json!({"opened": ok, "console_user": user}))
}

/// `networksetup -listallhardwareports` → interfaces with a MAC address.
pub fn parse_hardware_ports(text: &str) -> Vec<MacAddr> {
    let mut out = Vec::new();
    let (mut port, mut dev) = (String::new(), String::new());
    for line in text.lines() {
        if let Some(v) = line.strip_prefix("Hardware Port: ") {
            port = v.trim().to_string();
        } else if let Some(v) = line.strip_prefix("Device: ") {
            dev = v.trim().to_string();
        } else if let Some(v) = line.strip_prefix("Ethernet Address: ") {
            let mac = v.trim().to_lowercase();
            if valid_mac(&mac) {
                let lower = port.to_lowercase();
                let wired = !(lower.contains("wi-fi")
                    || lower.contains("airport")
                    || lower.contains("bluetooth"));
                out.push(MacAddr {
                    iface: dev.clone(),
                    mac,
                    wired,
                });
            }
        }
    }
    out
}

pub fn mac_addresses() -> Vec<MacAddr> {
    let (_, out, _) = run_cmd("/usr/sbin/networksetup", &["-listallhardwareports"]);
    parse_hardware_ports(&out)
}

/// Remove what the package installed (CLAUDE.md §5.2 `ctl uninstall`).
pub fn uninstall_extras() -> Result<Option<String>, CtlError> {
    let _ = std::fs::remove_file("/usr/local/bin/bn-backup-agent");
    let app = Path::new("/Applications/BNBackupAgent.app");
    if app.exists() {
        std::fs::remove_dir_all(app)?;
    }
    let _ = run_cmd(
        "/usr/sbin/pkgutil",
        &["--forget", "ar.bleiben.bn-backup-agent"],
    );
    Ok(None)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plist_rendering() {
        let p = render_plist(
            "sofia",
            MACOS_EXECUTABLE,
            Path::new("/Library/Application Support/BNBackupAgent/users/sofia/state/agent.log"),
        );
        assert!(p.contains("<string>ar.bleiben.bn-backup-agent.sofia</string>"));
        assert!(p.contains("<key>UserName</key>\n  <string>sofia</string>"));
        assert!(p.contains("<key>RunAtLoad</key>\n  <false/>"));
        assert!(!p.contains("KeepAlive"));
        assert!(!p.contains("StartInterval"));
        assert!(p.contains(&format!(
            "<string>{MACOS_EXECUTABLE}</string>\n    <string>run</string>"
        )));
        if Path::new("/usr/bin/plutil").exists() {
            let dir = tempfile::tempdir().unwrap();
            let f = dir.path().join("x.plist");
            std::fs::write(&f, &p).unwrap();
            let (ok, out, err) = run_cmd("/usr/bin/plutil", &["-lint", &f.to_string_lossy()]);
            assert!(ok, "{out}{err}");
        }
    }

    #[test]
    fn launchctl_state() {
        let out = "system/ar.bleiben.bn-backup-agent.sofia = {\n\tactive count = 1\n\tstate = running\n\tpid = 42\n}";
        assert_eq!(parse_state(out).as_deref(), Some("running"));
        assert_eq!(
            parse_state("\tstate = not running\n").as_deref(),
            Some("not running")
        );
        assert_eq!(parse_state("nothing"), None);
    }

    #[test]
    fn hardware_ports() {
        let text =
            "\nHardware Port: Ethernet\nDevice: en0\nEthernet Address: AA:BB:CC:DD:EE:01\n\n\
                    Hardware Port: Wi-Fi\nDevice: en1\nEthernet Address: aa:bb:cc:dd:ee:02\n\n\
                    Hardware Port: Thunderbolt Bridge\nDevice: bridge0\nEthernet Address: N/A\n";
        let m = parse_hardware_ports(text);
        assert_eq!(m.len(), 2);
        assert_eq!(
            m[0],
            MacAddr {
                iface: "en0".into(),
                mac: "aa:bb:cc:dd:ee:01".into(),
                wired: true
            }
        );
        assert!(!m[1].wired);
    }
}
