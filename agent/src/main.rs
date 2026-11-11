// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! bn-backup-agent: the agent of bleiben Backup Orchestrator.
//!
//! `ctl …` is the control half (root, through sudo, over SSH from the server).
//! `run` is the working half (started only by launchd or systemd, as the user).

mod awake;
mod classify;
mod ctl;
mod info;
mod job;
mod paths;
mod platform;
mod probe;
mod result;
mod rsync;
mod run;
mod sudoers;
mod util;
mod wol;

use clap::{Parser, Subcommand};

#[derive(Parser, Debug)]
#[command(
    name = "bn-backup-agent",
    version,
    about = "bleiben Backup Orchestrator agent"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Control commands for the backup server (run as root).
    #[command(subcommand)]
    Ctl(ctl::CtlCmd),
    /// Run the current job. Started only by launchd or systemd, as that user.
    Run {
        #[arg(long)]
        user: String,
    },
}

fn main() {
    let cli = Cli::parse();
    let code = match cli.cmd {
        Cmd::Ctl(cmd) => ctl::main(cmd),
        Cmd::Run { user } => run::main(&user),
    };
    std::process::exit(code);
}
