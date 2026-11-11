// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `ctl`: the control half. Runs as root through sudo; never reads user data.
//! Every command prints exactly one JSON object (CLAUDE.md §5.2).

use std::io::Read;

use clap::Subcommand;
use serde_json::{json, Value};

use crate::paths::{Layout, Os};
use crate::util::{is_root, valid_user_name, CtlError};

pub mod dispatch;
pub mod fda;
pub mod info;
pub mod log;
pub mod ping;
pub mod result;
pub mod setup;
pub mod start;
pub mod stop;
pub mod submit;
pub mod uninstall;
pub mod user;

#[derive(Subcommand, Debug, Clone, PartialEq, Eq)]
pub enum CtlCmd {
    /// One-time setup. Run by the operator with their password, never through the control key.
    Setup(setup::SetupArgs),
    /// Answer "ok"; tests the control connection.
    Ping,
    /// Version, protocol range, OS, network addresses, users set up and jobs running.
    Info,
    /// Set up a user: folders, push key and (macOS) the per-user job.
    UserAdd { user: String },
    /// Remove a user's job and files.
    UserRemove { user: String },
    /// Read a job from standard input, validate it and store it.
    Submit { user: String },
    /// Ask launchd or systemd to start the user's job.
    Start { user: String },
    /// Stop the user's running job.
    Stop { user: String },
    /// Print the user's result file.
    Result { user: String },
    /// The last 2000 lines of a module's rsync log.
    Log { user: String, module: String },
    /// macOS: open the Full Disk Access settings on the screen.
    OpenFdaSettings,
    /// The forced command of the control key. Never called by a person.
    SshDispatch {
        #[arg(allow_hyphen_values = true)]
        command: String,
    },
    /// Remove everything the agent installed. Run by the operator with their password.
    Uninstall,
}

/// What a command prints.
#[derive(Debug, Clone, PartialEq)]
pub enum Output {
    Json(Value),
    /// Printed verbatim (the result file).
    Raw(String),
}

pub fn ok() -> Output {
    Output::Json(json!({"ok": true}))
}

pub fn check_user(user: &str) -> Result<(), CtlError> {
    if valid_user_name(user) {
        Ok(())
    } else {
        Err(CtlError::new(
            "bad_user",
            format!("invalid user name {user:?}"),
        ))
    }
}

pub fn main(cmd: CtlCmd) -> i32 {
    if !is_root() {
        return emit(Err(CtlError::new(
            "not_root",
            "ctl must run as root (through sudo)",
        )));
    }
    let layout = Layout::system();
    emit(execute(&layout, Os::current(), cmd, &mut std::io::stdin()))
}

/// Print the output (or the error) and return the exit code.
pub fn emit(result: Result<Output, CtlError>) -> i32 {
    match result {
        Ok(Output::Json(v)) => {
            println!("{v}");
            0
        }
        Ok(Output::Raw(text)) => {
            print!("{text}");
            if !text.ends_with('\n') {
                println!();
            }
            0
        }
        Err(e) => {
            println!("{}", e.to_json());
            1
        }
    }
}

pub fn execute(
    layout: &Layout,
    os: Os,
    cmd: CtlCmd,
    stdin: &mut dyn Read,
) -> Result<Output, CtlError> {
    match cmd {
        CtlCmd::Setup(args) => setup::run(layout, os, &args),
        CtlCmd::Ping => ping::run(),
        CtlCmd::Info => info::run(layout, os),
        CtlCmd::UserAdd { user } => user::add(layout, &user),
        CtlCmd::UserRemove { user } => user::remove(layout, &user),
        CtlCmd::Submit { user } => submit::run(layout, &user, stdin),
        CtlCmd::Start { user } => start::run(layout, &user),
        CtlCmd::Stop { user } => stop::run(&user),
        CtlCmd::Result { user } => result::run(layout, &user),
        CtlCmd::Log { user, module } => log::run(layout, &user, &module),
        CtlCmd::OpenFdaSettings => fda::run(),
        CtlCmd::SshDispatch { command } => dispatch::run(layout, os, &command, stdin),
        CtlCmd::Uninstall => uninstall::run(layout, os),
    }
}
