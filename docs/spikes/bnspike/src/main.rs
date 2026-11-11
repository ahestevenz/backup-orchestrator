// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! Phase 0 spike helper (spikes S1, S2, S4, S9). Throwaway: not part of v2.
//!
//! Usage: `bnspike probe DIR [--hold SECS] [-- RSYNC_ARGS...]`
//!
//! Prints which user it runs as, whether it holds Full Disk Access (by
//! opening the system TCC database, like the real agent's probe), and whether
//! it can list DIR. With RSYNC_ARGS it then runs the rsync bundled next to it
//! (`../Resources/rsync` inside the app) as a child process. With `--hold` it
//! stays alive for SECS seconds at the end, so `launchctl print` can be
//! checked while it runs.

use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::{self, Command};
use std::thread::sleep;
use std::time::Duration;

const TCC_DB: &str = "/Library/Application Support/com.apple.TCC/TCC.db";

/// Change this text and rebuild to get a new code signature (spike S4).
const BUILD_TAG: &str = "build-1";

fn usage() -> ! {
    eprintln!("usage: bnspike probe DIR [--hold SECS] [-- RSYNC_ARGS...]");
    process::exit(64);
}

fn run_text(program: &str, args: &[&str]) -> String {
    Command::new(program)
        .args(args)
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_else(|e| format!("? ({e})"))
}

fn bundled_rsync() -> PathBuf {
    let exe = env::current_exe().expect("cannot find own executable");
    // .../BNSpike.app/Contents/MacOS/bnspike -> .../BNSpike.app/Contents/Resources/rsync
    exe.parent()
        .and_then(|macos| macos.parent())
        .map(|contents| contents.join("Resources/rsync"))
        .expect("bnspike must run from inside BNSpike.app")
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.len() < 2 || args[0] != "probe" {
        usage();
    }
    let dir = &args[1];
    let mut hold: u64 = 0;
    let mut rsync_args: Vec<String> = Vec::new();
    let mut i = 2;
    while i < args.len() {
        match args[i].as_str() {
            "--hold" => {
                hold = args
                    .get(i + 1)
                    .and_then(|s| s.parse().ok())
                    .unwrap_or_else(|| usage());
                i += 2;
            }
            "--" => {
                rsync_args = args[i + 1..].to_vec();
                break;
            }
            _ => usage(),
        }
    }

    println!(
        "--- bnspike {BUILD_TAG} pid={} at {}",
        process::id(),
        run_text("/bin/date", &["-u", "+%Y-%m-%dT%H:%M:%SZ"])
    );
    println!("user: {}", run_text("/usr/bin/id", &["-un"]));

    match fs::File::open(TCC_DB) {
        Ok(_) => println!("fda: granted"),
        Err(e) => println!("fda: denied ({e})"),
    }

    match fs::read_dir(dir) {
        Ok(mut entries) => match entries.next() {
            Some(Ok(entry)) => println!("read {dir}: ok (first entry {:?})", entry.file_name()),
            Some(Err(e)) => println!("read {dir}: error ({e})"),
            None => println!("read {dir}: ok (empty)"),
        },
        Err(e) => println!("read {dir}: error ({e})"),
    }

    if !rsync_args.is_empty() {
        let rsync = bundled_rsync();
        println!("running: {} {}", rsync.display(), rsync_args.join(" "));
        match Command::new(&rsync).args(&rsync_args).status() {
            Ok(status) => match status.code() {
                Some(code) => println!("rsync exit: {code}"),
                None => println!("rsync exit: killed by a signal"),
            },
            Err(e) => println!("rsync could not start: {e}"),
        }
    }

    if hold > 0 {
        println!("holding {hold} s");
        sleep(Duration::from_secs(hold));
    }
    println!("done");
}
