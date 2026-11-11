// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! Turning an rsync outcome into ok / failed + error kind (CLAUDE.md §5.10).
//!
//! The rows about the source pre-check, skipped modules, the job timeout and a
//! vanished drive are decided by the job runner (`run.rs`) before this is called.

use crate::paths::Os;
use crate::result::{ErrorKind, Status};

const DENIED: [&str; 2] = ["Operation not permitted", "Permission denied"];
const NETWORK_EXITS: [i32; 5] = [255, 5, 10, 12, 35];
const NETWORK_TEXT: [&str; 3] = ["ssh:", "Connection refused", "Could not resolve"];

fn denied(line: &str) -> bool {
    DENIED.iter().any(|d| line.contains(d))
}

/// Classify an rsync exit code and its stderr lines. First match wins.
pub fn classify(exit: Option<i32>, stderr: &[String], os: Os) -> (Status, Option<ErrorKind>) {
    if matches!(exit, Some(0) | Some(24)) {
        return (Status::Ok, None);
    }
    let failed = |k| (Status::Failed, Some(k));
    if exit == Some(30) {
        return failed(ErrorKind::Stalled);
    }
    // The server refused the write. rsync tags its own lines with the role;
    // rrsync (on the server) reports its own refusal before rsync starts.
    // rsync 3.4 writes the server-side roles capitalised ("[Receiver]"), so
    // compare without case.
    let server_side = |l: &String| {
        let lower = l.to_lowercase();
        (lower.contains("[receiver]")
            || lower.contains("[generator]")
            || lower.contains("rrsync error"))
            && denied(l)
    };
    if stderr.iter().any(server_side) {
        return failed(ErrorKind::ServerDenied);
    }
    let network_text = stderr
        .iter()
        .any(|l| NETWORK_TEXT.iter().any(|t| l.contains(t)));
    if exit.is_some_and(|c| NETWORK_EXITS.contains(&c)) || network_text {
        return failed(ErrorKind::Network);
    }
    if exit == Some(23) {
        if os == Os::MacOs && stderr.iter().any(|l| l.contains("Operation not permitted")) {
            return failed(ErrorKind::Tcc);
        }
        if stderr.iter().any(|l| l.contains("Permission denied")) {
            return failed(ErrorKind::Permission);
        }
    }
    failed(ErrorKind::Other)
}

/// The last 8 non-empty stderr lines, joined with newlines.
pub fn message(stderr: &[String]) -> String {
    let lines: Vec<&str> = stderr
        .iter()
        .map(|s| s.trim_end())
        .filter(|s| !s.is_empty())
        .collect();
    lines[lines.len().saturating_sub(8)..].join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    fn kind(exit: Option<i32>, err: &[&str], os: Os) -> Option<ErrorKind> {
        classify(exit, &lines(err), os).1
    }

    #[test]
    fn ok_codes() {
        assert_eq!(classify(Some(0), &[], Os::MacOs), (Status::Ok, None));
        assert_eq!(classify(Some(24), &[], Os::Linux), (Status::Ok, None));
    }

    #[test]
    fn table_rows() {
        use ErrorKind::*;
        assert_eq!(
            kind(Some(30), &["timeout in data send"], Os::Linux),
            Some(Stalled)
        );
        assert_eq!(
            kind(
                Some(23),
                &["rsync: [receiver] mkstemp \"x\" failed: Operation not permitted (1)"],
                Os::MacOs
            ),
            Some(ServerDenied)
        );
        assert_eq!(
            kind(
                Some(11),
                &["rsync: [Receiver] mkdir \"/x/docs\" failed: Permission denied (13)"],
                Os::Linux
            ),
            Some(ServerDenied)
        );
        assert_eq!(
            kind(
                Some(23),
                &["rsync: [generator] failed to set times: Permission denied"],
                Os::Linux
            ),
            Some(ServerDenied)
        );
        assert_eq!(
            kind(
                Some(1),
                &["rrsync error: unable to chdir to restricted dir: [Errno 1] Operation not permitted"],
                Os::MacOs
            ),
            Some(ServerDenied)
        );
        assert_eq!(kind(Some(255), &[], Os::Linux), Some(Network));
        assert_eq!(kind(Some(12), &[], Os::Linux), Some(Network));
        assert_eq!(
            kind(
                Some(1),
                &["ssh: Could not resolve hostname server"],
                Os::Linux
            ),
            Some(Network)
        );
        assert_eq!(
            kind(
                Some(23),
                &["rsync: [sender] opendir \"/Users/sofia/Documents\" failed: Operation not permitted (1)"],
                Os::MacOs
            ),
            Some(Tcc)
        );
        // On Linux, EPERM is a permission problem, not TCC.
        assert_eq!(
            kind(
                Some(23),
                &["rsync: [sender] send_files failed: Operation not permitted (1)"],
                Os::Linux
            ),
            Some(Other)
        );
        assert_eq!(
            kind(
                Some(23),
                &["rsync: [sender] opendir \"/x\" failed: Permission denied (13)"],
                Os::Linux
            ),
            Some(Permission)
        );
        assert_eq!(
            kind(Some(11), &["error in file IO"], Os::Linux),
            Some(Other)
        );
        assert_eq!(kind(None, &[], Os::Linux), Some(Other));
    }

    #[test]
    fn message_keeps_last_eight_non_empty_lines() {
        let err: Vec<String> = (1..=12)
            .map(|i| format!("line {i}"))
            .chain(["".into()])
            .collect();
        let m = message(&err);
        assert_eq!(m.lines().count(), 8);
        assert!(m.starts_with("line 5"));
        assert!(m.ends_with("line 12"));
    }
}
