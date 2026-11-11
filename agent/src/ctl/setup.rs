// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl setup`: the one-time host setup, run by the operator with their
//! password during bootstrap (CLAUDE.md §5.2, §5.6, §5.8, §5.11).

use clap::Args;
use nix::unistd::{Gid, Uid, User};
use serde_json::json;

use super::Output;
use crate::paths::{executable, AgentConfig, Layout, Os, CONTROL_KEY_COMMENT};
use crate::util::{atomic_write, ensure_dir, valid_host_key, valid_user_name, CtlError};

#[derive(Args, Debug, Clone, PartialEq, Eq)]
pub struct SetupArgs {
    /// The host's key in the server config.
    #[arg(long)]
    pub host_name: String,
    #[arg(long)]
    pub server_host: String,
    #[arg(long)]
    pub server_port: u16,
    /// The operator's account on the server (receives the pushes).
    #[arg(long)]
    pub server_user: String,
    /// The server's SSH host key as a known_hosts line.
    #[arg(long)]
    pub server_known_hosts_line: String,
    /// This host's admin account (gets the passwordless `ctl` rule and the control key).
    #[arg(long)]
    pub admin_user: String,
    /// The server's control public key.
    #[arg(long, allow_hyphen_values = true)]
    pub control_key: String,
}

/// The locked control-key line (§5.11): only `ctl ssh-dispatch` may run.
pub fn control_key_line(exe: &str, key: &str) -> Result<String, CtlError> {
    let mut words = key.split_whitespace();
    let (Some(kind), Some(data)) = (words.next(), words.next()) else {
        return Err(CtlError::new(
            "bad_key",
            "the control key must be '<type> <data> [comment]'",
        ));
    };
    let ok_chars = |s: &str| {
        s.chars()
            .all(|c| c.is_ascii_alphanumeric() || "+/=-@.".contains(c))
    };
    if !kind.starts_with("ssh-") && !kind.starts_with("ecdsa-")
        || !ok_chars(kind)
        || !ok_chars(data)
    {
        return Err(CtlError::new(
            "bad_key",
            "the control key is not a valid public key",
        ));
    }
    Ok(format!(
        "restrict,command=\"/usr/bin/sudo -n {exe} ctl ssh-dispatch \\\"$SSH_ORIGINAL_COMMAND\\\"\" {kind} {data} {CONTROL_KEY_COMMENT}"
    ))
}

/// Replace any earlier control-key line; keep every other line.
pub fn with_control_key(existing: &str, line: &str) -> String {
    let mut out = without_control_key(existing);
    out.push_str(line);
    out.push('\n');
    out
}

pub fn without_control_key(existing: &str) -> String {
    let suffix = format!(" {CONTROL_KEY_COMMENT}");
    let mut out: String = existing
        .lines()
        .filter(|l| !l.trim_end().ends_with(&suffix))
        .map(|l| format!("{l}\n"))
        .collect();
    if out.trim().is_empty() {
        out.clear();
    }
    out
}

/// Write the admin account's authorized_keys (0600 in ~/.ssh 0700, owned by the admin).
pub fn update_admin_authorized_keys(
    admin: &str,
    change: impl Fn(&str) -> String,
) -> Result<(), CtlError> {
    let pw = User::from_name(admin)
        .ok()
        .flatten()
        .ok_or_else(|| CtlError::new("no_such_user", format!("there is no account {admin:?}")))?;
    let owner = Some((pw.uid, pw.gid));
    let ssh = pw.dir.join(".ssh");
    ensure_dir(&ssh, 0o700, owner)?;
    let file = ssh.join("authorized_keys");
    let existing = std::fs::read_to_string(&file).unwrap_or_default();
    atomic_write(&file, change(&existing).as_bytes(), 0o600, owner)?;
    Ok(())
}

fn validate(a: &SetupArgs) -> Result<(), CtlError> {
    let bad = |m: &str| Err(CtlError::new("bad_args", m.to_string()));
    if !valid_host_key(&a.host_name) {
        return bad("--host-name is not a valid host key");
    }
    if !valid_user_name(&a.server_user) || !valid_user_name(&a.admin_user) {
        return bad("--server-user and --admin-user must be account names");
    }
    if a.server_host.is_empty() || a.server_host.contains(char::is_whitespace) {
        return bad("--server-host is not a host name");
    }
    if a.server_port == 0 {
        return bad("--server-port must be a port number");
    }
    let kh = a.server_known_hosts_line.trim();
    if kh.split_whitespace().count() < 3 || kh.contains('\n') {
        return bad("--server-known-hosts-line must be '<host> <type> <key>'");
    }
    Ok(())
}

pub fn run(layout: &Layout, os: Os, a: &SetupArgs) -> Result<Output, CtlError> {
    validate(a)?;
    let exe = executable(os);
    let key_line = control_key_line(exe, &a.control_key)?;
    let root = Some((Uid::from_raw(0), Gid::from_raw(0)));

    ensure_dir(&layout.home, 0o755, root)?;
    ensure_dir(&layout.users_dir(), 0o755, root)?;
    let cfg = AgentConfig {
        server_host: a.server_host.clone(),
        server_port: a.server_port,
        server_user: a.server_user.clone(),
        admin_user: a.admin_user.clone(),
        host_name: a.host_name.clone(),
    };
    atomic_write(&layout.agent_toml(), cfg.to_toml().as_bytes(), 0o644, root)?;
    let kh = format!("{}\n", a.server_known_hosts_line.trim());
    atomic_write(&layout.known_hosts(), kh.as_bytes(), 0o644, root)?;

    crate::sudoers::install(&a.admin_user, exe)?;
    update_admin_authorized_keys(&a.admin_user, |old| with_control_key(old, &key_line))?;

    let (wol, detail) = crate::wol::enable(os);
    Ok(Output::Json(
        json!({"ok": true, "wol": wol, "wol_detail": detail}),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    const KEY: &str = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample bn-backup-server";

    #[test]
    fn locked_line() {
        let l = control_key_line("/usr/bin/bn-backup-agent", KEY).unwrap();
        assert_eq!(
            l,
            "restrict,command=\"/usr/bin/sudo -n /usr/bin/bn-backup-agent ctl ssh-dispatch \
             \\\"$SSH_ORIGINAL_COMMAND\\\"\" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample bn-backup-server"
        );
        assert!(control_key_line("/x", "nonsense").is_err());
        assert!(control_key_line("/x", "ssh-ed25519 AAAA\"evil").is_err());
    }

    #[test]
    fn replaces_old_line_keeps_others() {
        let existing = "ssh-ed25519 AAAAmine me@laptop\n\
                        restrict,command=\"old\" ssh-ed25519 AAAAold bn-backup-server\n\
                        ssh-rsa AAAAother other@desk\n";
        let new = with_control_key(existing, "NEW bn-backup-server");
        assert_eq!(
            new,
            "ssh-ed25519 AAAAmine me@laptop\nssh-rsa AAAAother other@desk\nNEW bn-backup-server\n"
        );
        assert_eq!(
            with_control_key("", "NEW bn-backup-server"),
            "NEW bn-backup-server\n"
        );
        assert_eq!(
            without_control_key(&new),
            "ssh-ed25519 AAAAmine me@laptop\nssh-rsa AAAAother other@desk\n"
        );
    }

    #[test]
    fn argument_validation() {
        let a = SetupArgs {
            host_name: "athena".into(),
            server_host: "macmini.home.lan".into(),
            server_port: 22,
            server_user: "ariel".into(),
            server_known_hosts_line: "macmini.home.lan ssh-ed25519 AAAAhost".into(),
            admin_user: "ariel".into(),
            control_key: KEY.into(),
        };
        assert!(validate(&a).is_ok());
        let mut b = a.clone();
        b.host_name = "Athena".into();
        assert!(validate(&b).is_err());
        let mut b = a.clone();
        b.server_known_hosts_line = "macmini".into();
        assert!(validate(&b).is_err());
    }
}
