// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! Turn on Wake-on-LAN during `ctl setup` (CLAUDE.md §5.8, D-24). Never fails setup.

use crate::paths::Os;
use crate::platform::current::mac_addresses;
use crate::util::run_cmd;

pub const LINK_FILE: &str = "/etc/systemd/network/50-bn-backup-wol.link";
pub const LINK_CONTENT: &str = "[Match]\nType=ether\n\n[Link]\nWakeOnLan=magic\n";

/// Returns (`enabled` | `partial` | `not_supported`, detail).
pub fn enable(os: Os) -> (&'static str, String) {
    match os {
        Os::MacOs => {
            let (ok, _, err) = run_cmd("/usr/bin/pmset", &["-a", "womp", "1"]);
            if ok {
                ("enabled", "pmset womp 1".into())
            } else {
                ("partial", format!("pmset failed: {}", err.trim()))
            }
        }
        Os::Linux => linux(),
    }
}

/// `nmcli -t -f UUID,TYPE connection show` lines → UUIDs of wired connections.
pub fn wired_connections(nmcli_output: &str) -> Vec<String> {
    nmcli_output
        .lines()
        .filter_map(|l| l.split_once(':'))
        .filter(|(_, ty)| *ty == "802-3-ethernet")
        .map(|(uuid, _)| uuid.to_string())
        .collect()
}

fn linux() -> (&'static str, String) {
    let (nm_active, _, _) = run_cmd("systemctl", &["is-active", "--quiet", "NetworkManager"]);
    if nm_active {
        let (_, out, _) = run_cmd("nmcli", &["-t", "-f", "UUID,TYPE", "connection", "show"]);
        let uuids = wired_connections(&out);
        if uuids.is_empty() {
            return (
                "not_supported",
                "NetworkManager has no wired connection".into(),
            );
        }
        let failed: Vec<&String> = uuids
            .iter()
            .filter(|u| {
                !run_cmd(
                    "nmcli",
                    &[
                        "connection",
                        "modify",
                        u,
                        "802-3-ethernet.wake-on-lan",
                        "magic",
                    ],
                )
                .0
            })
            .collect();
        return if failed.is_empty() {
            (
                "enabled",
                format!("NetworkManager: {} wired connection(s)", uuids.len()),
            )
        } else if failed.len() < uuids.len() {
            ("partial", format!("NetworkManager: failed for {failed:?}"))
        } else {
            (
                "partial",
                "NetworkManager: could not set wake-on-lan".into(),
            )
        };
    }
    if !mac_addresses().iter().any(|m| m.wired) {
        return ("not_supported", "no wired network interface".into());
    }
    let dir = std::path::Path::new(LINK_FILE).parent().expect("parent");
    let written =
        std::fs::create_dir_all(dir).and_then(|_| std::fs::write(LINK_FILE, LINK_CONTENT));
    match written {
        Ok(()) => (
            "enabled",
            format!("{LINK_FILE} (applies from the next boot)"),
        ),
        Err(e) => ("partial", format!("cannot write {LINK_FILE}: {e}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nmcli_parsing() {
        let out = "1111-aaaa:802-3-ethernet\n2222-bbbb:802-11-wireless\n3333-cccc:802-3-ethernet\n";
        assert_eq!(wired_connections(out), ["1111-aaaa", "3333-cccc"]);
    }
}
