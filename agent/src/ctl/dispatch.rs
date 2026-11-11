// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl ssh-dispatch "<command>"`: the forced command of the control key
//! (CLAUDE.md §5.11, D-48). It runs one allowed `ctl` command and nothing else.

use std::io::Read;

use clap::Parser;

use super::{CtlCmd, Output};
use crate::paths::{Layout, Os};
use crate::util::CtlError;

/// What the control key may run. Never `setup`, `uninstall` or `ssh-dispatch`.
pub const ALLOWED: [&str; 10] = [
    "ping",
    "info",
    "user-add",
    "user-remove",
    "submit",
    "start",
    "stop",
    "result",
    "log",
    "open-fda-settings",
];

#[derive(Parser, Debug)]
#[command(no_binary_name = true)]
struct Dispatched {
    #[command(subcommand)]
    cmd: CtlCmd,
}

pub fn parse(command: &str) -> Result<CtlCmd, CtlError> {
    if command.trim().is_empty() {
        return Err(CtlError::new("no_command", "this key cannot open a shell"));
    }
    let words = shell_words::split(command)
        .map_err(|_| CtlError::new("not_allowed", "the command could not be parsed"))?;
    let allowed = words.first().map(String::as_str) == Some("ctl")
        && words.get(1).is_some_and(|w| ALLOWED.contains(&w.as_str()));
    if !allowed {
        return Err(CtlError::new(
            "not_allowed",
            "only bn-backup-agent ctl commands may run",
        ));
    }
    Dispatched::try_parse_from(&words[1..])
        .map(|d| d.cmd)
        .map_err(|e| {
            let first = e.to_string().lines().next().unwrap_or_default().to_string();
            CtlError::new("bad_command", first)
        })
}

pub fn run(
    layout: &Layout,
    os: Os,
    command: &str,
    stdin: &mut dyn Read,
) -> Result<Output, CtlError> {
    let cmd = parse(command)?;
    super::execute(layout, os, cmd, stdin)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowed_commands() {
        assert_eq!(parse("ctl ping").unwrap(), CtlCmd::Ping);
        assert_eq!(
            parse("ctl submit sofia").unwrap(),
            CtlCmd::Submit {
                user: "sofia".into()
            }
        );
        assert_eq!(
            parse("ctl log sofia 'my module'").unwrap(),
            CtlCmd::Log {
                user: "sofia".into(),
                module: "my module".into()
            }
        );
    }

    #[test]
    fn refused_commands() {
        for (cmd, code) in [
            ("", "no_command"),
            ("   ", "no_command"),
            ("ctl setup --host-name x", "not_allowed"),
            ("ctl uninstall", "not_allowed"),
            ("ctl ssh-dispatch 'ctl ping'", "not_allowed"),
            ("run --user sofia", "not_allowed"),
            ("bash -c id", "not_allowed"),
            ("ctl", "not_allowed"),
            ("ctl ping 'unterminated", "not_allowed"),
            ("ctl ping extra", "bad_command"),
            ("ctl start", "bad_command"),
        ] {
            assert_eq!(parse(cmd).unwrap_err().code, code, "{cmd:?}");
        }
    }

    #[test]
    fn hostile_strings_stay_single_arguments() {
        // No shell ever sees the string: `; id` is just part of an argument.
        // shell-words keeps ";" in the word, so "ping;" is not an allowed command.
        assert_eq!(parse("ctl ping; id").unwrap_err().code, "not_allowed");
        assert_eq!(
            parse("ctl stop 'sofia; rm -rf /'").unwrap(),
            CtlCmd::Stop {
                user: "sofia; rm -rf /".into()
            }
        );
        // ...and that user name is then refused by the command itself.
        let d = tempfile::tempdir().unwrap();
        let l = Layout {
            home: d.path().into(),
        };
        let err = run(&l, Os::Linux, "ctl result '../../etc'", &mut &b""[..]).unwrap_err();
        assert_eq!(err.code, "bad_user");
        let err = run(&l, Os::Linux, "ctl stop '$(id)'", &mut &b""[..]).unwrap_err();
        assert_eq!(err.code, "bad_user");
    }

    #[test]
    fn stdin_reaches_submit() {
        let d = tempfile::tempdir().unwrap();
        let l = Layout {
            home: d.path().into(),
        };
        std::fs::write(l.agent_toml(), crate::job::tests::cfg().to_toml()).unwrap();
        std::fs::create_dir_all(l.state_dir("sofia")).unwrap();
        std::fs::write(l.key("sofia"), "k").unwrap();
        // `submit::accept` is the part of `submit` that reads stdin.
        let mut stdin = crate::job::tests::JOB.as_bytes();
        let job = super::super::submit::accept(&l, "sofia", &mut stdin).unwrap();
        assert_eq!(job.user, "sofia");
        let mut empty: &[u8] = b"";
        assert_eq!(
            super::super::submit::accept(&l, "sofia", &mut empty)
                .unwrap_err()
                .code,
            "bad_job"
        );
    }
}
