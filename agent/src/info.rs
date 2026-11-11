// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl info`: what this agent is and what it has set up (CLAUDE.md §5.2).

use serde_json::{json, Value};

use crate::job::{PROTOCOL_MAX, PROTOCOL_MIN};
use crate::paths::{rsync_path, Layout, Os};
use crate::platform::current;
use crate::util::run_cmd;

/// `rsync  version 3.4.1  protocol version 32` → `3.4.1`.
pub fn parse_rsync_version(first_line: &str) -> Option<String> {
    let mut words = first_line.split_whitespace();
    if words.next()? != "rsync" {
        return None;
    }
    words.find(|w| *w == "version")?;
    words.next().map(str::to_string)
}

pub fn arch(os: Os) -> &'static str {
    match (os, std::env::consts::ARCH) {
        (Os::MacOs, "aarch64") => "arm64",
        (_, "x86_64") => "x86_64",
        (_, "aarch64") => "aarch64",
        (_, other) => other,
    }
}

pub fn gather(layout: &Layout, os: Os) -> Value {
    let rsync = rsync_path();
    let (_, out, _) = run_cmd(&rsync.to_string_lossy(), &["--version"]);
    let rsync_version = out.lines().next().and_then(parse_rsync_version);
    let hostname = nix::unistd::gethostname()
        .map(|h| h.to_string_lossy().into_owned())
        .unwrap_or_default();
    let users = layout.users();
    let running: Vec<&String> = users.iter().filter(|u| current::is_running(u)).collect();
    json!({
        "agent_version": env!("CARGO_PKG_VERSION"),
        "protocol_min": PROTOCOL_MIN,
        "protocol_max": PROTOCOL_MAX,
        "os": os.name(),
        "arch": arch(os),
        "hostname": hostname,
        "mac_addresses": current::mac_addresses(),
        "rsync_path": rsync.to_string_lossy(),
        "rsync_version": rsync_version,
        "configured": layout.agent_toml().exists(),
        "users": users,
        "running": running,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rsync_version_line() {
        assert_eq!(
            parse_rsync_version("rsync  version 3.4.1  protocol version 32").as_deref(),
            Some("3.4.1")
        );
        assert_eq!(parse_rsync_version("openrsync: protocol version 29"), None);
    }

    #[test]
    fn arch_names() {
        let a = arch(Os::current());
        assert!(["arm64", "x86_64", "aarch64"].contains(&a), "{a}");
    }
}
