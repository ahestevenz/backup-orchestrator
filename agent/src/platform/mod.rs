// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! launchd (macOS) and systemd (Linux). Both modules compile everywhere so
//! their rendering can be tested on either OS; `current` is the one in use.

pub mod linux;
pub mod macos;

#[cfg(not(target_os = "macos"))]
pub use linux as current;
#[cfg(target_os = "macos")]
pub use macos as current;

use serde::Serialize;

/// A network interface's hardware address, reported by `ctl info`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MacAddr {
    pub iface: String,
    pub mac: String,
    pub wired: bool,
}

pub fn valid_mac(s: &str) -> bool {
    let parts: Vec<&str> = s.split(':').collect();
    parts.len() == 6
        && parts
            .iter()
            .all(|p| p.len() == 2 && p.chars().all(|c| c.is_ascii_hexdigit()))
        && s != "00:00:00:00:00:00"
}
