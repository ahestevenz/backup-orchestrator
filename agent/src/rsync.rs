// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! Building rsync command lines and running rsync (CLAUDE.md §5.9).

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

/// Most suspect files listed per module by the verify pass.
pub const MAX_SUSPECT_FILES: usize = 500;
/// Most stderr lines kept for classification.
const MAX_STDERR_LINES: usize = 10_000;

/// Everything needed to talk to the server.
#[derive(Debug, Clone)]
pub struct Target {
    pub user: String,
    pub host: String,
    pub port: u16,
    pub key: PathBuf,
    pub known_hosts: PathBuf,
}

impl Target {
    /// `user@host:path`, with brackets around an IPv6 literal.
    pub fn remote(&self, path: &str) -> String {
        if self.host.contains(':') {
            format!("{}@[{}]:{}", self.user, self.host, path)
        } else {
            format!("{}@{}:{}", self.user, self.host, path)
        }
    }

    /// The `-e` value: one argument that rsync splits on spaces, honouring
    /// quotes. Paths are quoted because the macOS agent home contains a space.
    pub fn ssh_command(&self) -> String {
        format!(
            "ssh -i {} -o {} -o StrictHostKeyChecking=yes -o BatchMode=yes \
             -o ConnectTimeout=15 -o ServerAliveInterval=30 -p {}",
            quote(&self.key.to_string_lossy()),
            quote(&format!(
                "UserKnownHostsFile={}",
                self.known_hosts.to_string_lossy()
            )),
            self.port
        )
    }
}

/// Quote a word for rsync's `-e` parser (spaces and quotes, no backslashes).
pub fn quote(word: &str) -> String {
    if !word.contains([' ', '\'', '"']) {
        word.to_string()
    } else if !word.contains('\'') {
        format!("'{word}'")
    } else {
        format!("\"{word}\"")
    }
}

/// Options shared by every transfer.
#[derive(Debug, Clone)]
pub struct Common {
    pub io_timeout_seconds: u64,
    pub partial: bool,
    pub dry_run: bool,
}

/// The common prefix of §5.9 (without the program itself).
pub fn common_args(target: &Target, opts: &Common, log_file: &Path, delete: bool) -> Vec<String> {
    let mut a: Vec<String> = vec![
        "--archive".into(),
        "--hard-links".into(),
        "--numeric-ids".into(),
        "--xattrs".into(),
    ];
    if delete {
        a.push("--delete".into());
    }
    a.push("-M--fake-super".into());
    a.push(format!("--log-file={}", log_file.display()));
    a.push("--out-format=%i %n".into());
    a.push("-e".into());
    a.push(target.ssh_command());
    a.push(format!("--timeout={}", opts.io_timeout_seconds));
    if opts.partial {
        a.push("--partial".into());
    }
    if opts.dry_run {
        a.push("--dry-run".into());
    }
    a
}

/// A `path` module: the folder itself (no trailing slash) into `<module>/`.
pub fn path_module_args(
    target: &Target,
    opts: &Common,
    log_file: &Path,
    module: &str,
    src_path: &str,
    excludes: &[String],
) -> Vec<String> {
    let mut a = common_args(target, opts, log_file, true);
    a.extend(excludes.iter().map(|e| format!("--exclude={e}")));
    a.push(src_path.trim_end_matches('/').to_string());
    a.push(target.remote(&format!("{module}/")));
    a
}

/// The verify pass (D-50): the same transfer with `--checksum --dry-run`.
pub fn verify_args(
    target: &Target,
    opts: &Common,
    log_file: &Path,
    module: &str,
    src_path: &str,
    excludes: &[String],
) -> Vec<String> {
    let opts = Common {
        dry_run: false,
        ..opts.clone()
    };
    let mut a = path_module_args(target, &opts, log_file, module, src_path, excludes);
    let at = a.len() - 2;
    a.insert(at, "--checksum".into());
    a.insert(at + 1, "--dry-run".into());
    a
}

/// Host-config transfer 1: `/etc/hosts` and `/etc/motd` into `<module>/`, no `--delete`.
pub fn host_files_args(
    target: &Target,
    opts: &Common,
    log_file: &Path,
    module: &str,
    files: &[String],
) -> Vec<String> {
    let mut a = common_args(target, opts, log_file, false);
    a.extend(files.iter().cloned());
    a.push(target.remote(&format!("{module}/")));
    a
}

/// Host-config transfer 2: the user's top-level dotfiles into `<module>/<user>/`.
/// Copying `$HOME/` with filter rules (instead of listing each dotfile) lets
/// `--delete` remove a dotfile that was deleted at the source.
pub fn dotfiles_args(
    target: &Target,
    opts: &Common,
    log_file: &Path,
    module: &str,
    user: &str,
    home: &Path,
) -> Vec<String> {
    let mut a = common_args(target, opts, log_file, true);
    a.extend(
        [
            "--exclude=.Trash",
            "--exclude=.cache",
            "--include=/.*",
            "--exclude=/*",
        ]
        .map(String::from),
    );
    a.push(format!("{}/", home.display()));
    a.push(target.remote(&format!("{module}/{user}/")));
    a
}

/// The probe's real write: a small folder into `.probe/` (§5.5).
pub fn probe_args(target: &Target, opts: &Common, log_file: &Path, dir: &Path) -> Vec<String> {
    let mut a = common_args(target, opts, log_file, true);
    a.push("--recursive".into());
    a.push(format!("{}/", dir.display()));
    a.push(target.remote(".probe/"));
    a
}

/// A transferred file in `--out-format=%i %n` output.
pub fn is_transfer_line(line: &str) -> bool {
    line.starts_with(">f") || line.starts_with("<f")
}

/// The verify pass: a file whose content differs although size and time match
/// (itemize `<fc..…`: `c` 3rd, `s` and `t` 4th and 5th are `.`). Returns its name.
/// A push marks files with `<` (sent); `>` is accepted too, for completeness.
pub fn suspect_name(line: &str) -> Option<&str> {
    let b = line.as_bytes();
    if b.len() > 12
        && (b[0] == b'<' || b[0] == b'>')
        && b[1] == b'f'
        && b[2] == b'c'
        && b[3] == b'.'
        && b[4] == b'.'
    {
        line.split_once(' ').map(|(_, name)| name)
    } else {
        None
    }
}

/// Bytes sent, from the `sent N bytes` summary lines of the log file.
pub fn sent_bytes(log_text: &str) -> u64 {
    log_text
        .lines()
        .filter_map(|l| {
            let rest = &l[l.find("sent ")? + 5..];
            let num = rest.split_whitespace().next()?;
            if !rest.contains("bytes") {
                return None;
            }
            num.chars()
                .filter(char::is_ascii_digit)
                .collect::<String>()
                .parse::<u64>()
                .ok()
        })
        .sum()
}

/// Why rsync was stopped early.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Killed {
    /// The job's overall time limit passed.
    Deadline,
    /// The agent was asked to stop (SIGTERM from launchd or systemd).
    Stopped,
}

#[derive(Debug, Clone, Default)]
pub struct Outcome {
    pub exit: Option<i32>,
    pub killed: Option<Killed>,
    pub stderr: Vec<String>,
    pub transferred: u64,
    pub suspect_count: u64,
    pub suspects: Vec<String>,
    pub spawn_error: Option<String>,
}

impl Outcome {
    pub fn acceptable(&self) -> bool {
        self.killed.is_none() && matches!(self.exit, Some(0) | Some(24))
    }
}

/// Runs rsync. A trait so the job logic can be tested without rsync.
pub trait Runner {
    fn run(&mut self, args: &[String], deadline: Option<Instant>) -> Outcome;
}

/// Set by the SIGTERM handler; checked while rsync runs.
pub static STOP: AtomicBool = AtomicBool::new(false);

pub struct RealRunner {
    pub rsync: PathBuf,
}

enum Line {
    Out(String),
    Err(String),
}

impl Runner for RealRunner {
    fn run(&mut self, args: &[String], deadline: Option<Instant>) -> Outcome {
        let mut out = Outcome::default();
        let mut child = match Command::new(&self.rsync)
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                out.spawn_error = Some(format!("cannot start {}: {e}", self.rsync.display()));
                return out;
            }
        };
        let (tx, rx) = mpsc::channel();
        let stdout = child.stdout.take().expect("piped stdout");
        let stderr = child.stderr.take().expect("piped stderr");
        let tx2 = tx.clone();
        let t_out = thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let _ = tx.send(Line::Out(line));
            }
        });
        let t_err = thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                let _ = tx2.send(Line::Err(line));
            }
        });

        let handle = |line: Line, out: &mut Outcome| match line {
            Line::Out(l) => {
                if is_transfer_line(&l) {
                    out.transferred += 1;
                }
                if let Some(name) = suspect_name(&l) {
                    out.suspect_count += 1;
                    if out.suspects.len() < MAX_SUSPECT_FILES {
                        out.suspects.push(name.to_string());
                    }
                }
            }
            Line::Err(l) => {
                if out.stderr.len() >= MAX_STDERR_LINES {
                    out.stderr.remove(0);
                }
                out.stderr.push(l);
            }
        };

        let status = loop {
            while let Ok(line) = rx.try_recv() {
                handle(line, &mut out);
            }
            match child.try_wait() {
                Ok(Some(status)) => break Some(status),
                Ok(None) => {}
                Err(_) => break None,
            }
            let reason = if STOP.load(Ordering::SeqCst) {
                Some(Killed::Stopped)
            } else if deadline.is_some_and(|d| Instant::now() >= d) {
                Some(Killed::Deadline)
            } else {
                None
            };
            if let Some(reason) = reason {
                out.killed = Some(reason);
                terminate(&mut child);
                break child.wait().ok();
            }
            thread::sleep(Duration::from_millis(100));
        };
        let _ = t_out.join();
        let _ = t_err.join();
        while let Ok(line) = rx.try_recv() {
            handle(line, &mut out);
        }
        out.exit = status.and_then(|s| s.code());
        out
    }
}

/// SIGTERM, then SIGKILL after 10 seconds.
fn terminate(child: &mut std::process::Child) {
    let pid = nix::unistd::Pid::from_raw(child.id() as i32);
    let _ = nix::sys::signal::kill(pid, nix::sys::signal::Signal::SIGTERM);
    let until = Instant::now() + Duration::from_secs(10);
    while Instant::now() < until {
        if let Ok(Some(_)) = child.try_wait() {
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn target() -> Target {
        Target {
            user: "ariel".into(),
            host: "server.home.lan".into(),
            port: 22,
            key: "/Library/Application Support/BNBackupAgent/users/sofia/state/id_ed25519".into(),
            known_hosts: "/Library/Application Support/BNBackupAgent/server_known_hosts".into(),
        }
    }

    fn opts() -> Common {
        Common {
            io_timeout_seconds: 600,
            partial: true,
            dry_run: false,
        }
    }

    #[test]
    fn path_module_command_line() {
        let a = path_module_args(
            &target(),
            &opts(),
            Path::new("/s/rsync-docs.log"),
            "sofia-documents",
            "/Users/sofia/Documents",
            &[".DS_Store".into()],
        );
        assert_eq!(
            &a[..6],
            [
                "--archive",
                "--hard-links",
                "--numeric-ids",
                "--xattrs",
                "--delete",
                "-M--fake-super"
            ]
        );
        assert!(a.contains(&"--log-file=/s/rsync-docs.log".to_string()));
        assert!(a.contains(&"--out-format=%i %n".to_string()));
        assert!(a.contains(&"--timeout=600".to_string()));
        assert!(a.contains(&"--partial".to_string()));
        assert!(a.contains(&"--exclude=.DS_Store".to_string()));
        assert!(!a
            .iter()
            .any(|x| x == "--compress" || x == "--checksum" || x == "--dry-run"));
        assert!(!a.iter().any(|x| x == "--inplace" || x == "--append"));
        // No trailing slash on the source: the folder itself lands in the module.
        assert_eq!(a[a.len() - 2], "/Users/sofia/Documents");
        assert_eq!(a[a.len() - 1], "ariel@server.home.lan:sofia-documents/");
    }

    #[test]
    fn ssh_command_quotes_paths_with_spaces() {
        let e = target().ssh_command();
        assert!(e.starts_with(
            "ssh -i '/Library/Application Support/BNBackupAgent/users/sofia/state/id_ed25519' "
        ));
        assert!(e.contains(
            "-o 'UserKnownHostsFile=/Library/Application Support/BNBackupAgent/server_known_hosts'"
        ));
        assert!(e.contains("-o StrictHostKeyChecking=yes -o BatchMode=yes"));
        assert!(e.ends_with("-p 22"));
        assert_eq!(quote("/plain/path"), "/plain/path");
    }

    #[test]
    fn dry_run_and_no_partial() {
        let o = Common {
            dry_run: true,
            partial: false,
            ..opts()
        };
        let a = path_module_args(&target(), &o, Path::new("/l"), "m", "/x", &[]);
        assert!(a.contains(&"--dry-run".to_string()));
        assert!(!a.contains(&"--partial".to_string()));
    }

    #[test]
    fn verify_pass_adds_checksum_and_dry_run_only_there() {
        let a = verify_args(&target(), &opts(), Path::new("/v.log"), "m", "/x", &[]);
        assert_eq!(a.iter().filter(|x| *x == "--checksum").count(), 1);
        assert_eq!(a.iter().filter(|x| *x == "--dry-run").count(), 1);
        assert_eq!(a[a.len() - 2], "/x");
    }

    #[test]
    fn host_config_transfers() {
        let t = target();
        let a = host_files_args(
            &t,
            &opts(),
            Path::new("/l"),
            "sofia-athena",
            &["/etc/hosts".into(), "/etc/motd".into()],
        );
        assert!(!a.contains(&"--delete".to_string()));
        assert_eq!(a[a.len() - 1], "ariel@server.home.lan:sofia-athena/");
        let d = dotfiles_args(
            &t,
            &opts(),
            Path::new("/l"),
            "sofia-athena",
            "sofia",
            Path::new("/Users/sofia"),
        );
        assert!(d.contains(&"--delete".to_string()));
        let filters: Vec<&String> = d
            .iter()
            .filter(|x| x.starts_with("--exclude=") || x.starts_with("--include="))
            .collect();
        assert_eq!(
            filters,
            [
                "--exclude=.Trash",
                "--exclude=.cache",
                "--include=/.*",
                "--exclude=/*"
            ]
        );
        assert_eq!(d[d.len() - 2], "/Users/sofia/");
        assert_eq!(d[d.len() - 1], "ariel@server.home.lan:sofia-athena/sofia/");
    }

    #[test]
    fn ipv6_server() {
        let t = Target {
            host: "fd00::1".into(),
            ..target()
        };
        assert_eq!(t.remote("m/"), "ariel@[fd00::1]:m/");
    }

    #[test]
    fn itemize_parsing() {
        assert!(is_transfer_line(">f+++++++++ Photos/a.NEF"));
        assert!(!is_transfer_line("cd+++++++++ Photos/"));
        assert!(!is_transfer_line("*deleting   Photos/b.NEF"));
        assert_eq!(
            suspect_name(">fc........ Photos/s14.bin"),
            Some("Photos/s14.bin")
        );
        assert_eq!(
            suspect_name("<fc......... Photos/s14.bin"),
            Some("Photos/s14.bin")
        );
        assert_eq!(suspect_name(">fc.t...... Photos/x"), None);
        assert_eq!(suspect_name(">fcs....... Photos/x"), None);
        assert_eq!(suspect_name(">f..t...... Photos/x"), None);
    }

    #[test]
    fn sent_bytes_from_log() {
        let log = "2026/11/10 10:30:00 [1] >f+++++++++ a\n\
                   2026/11/10 10:30:01 [1] sent 1,234 bytes  received 56 bytes  total size 789\n\
                   2026/11/10 10:40:01 [2] sent 100 bytes  received 5 bytes  total size 9\n";
        assert_eq!(sent_bytes(log), 1334);
        assert_eq!(sent_bytes("nothing here"), 0);
    }

    #[test]
    fn real_runner_reports_exit_and_lines() {
        // `sh` stands in for rsync: prints itemize lines and an error, exits 23.
        let mut r = RealRunner {
            rsync: "/bin/sh".into(),
        };
        let script = "echo '>f+++++++++ a'; echo '>fc........ b'; echo 'oops' >&2; exit 23";
        let o = r.run(&["-c".into(), script.into()], None);
        assert_eq!(o.exit, Some(23));
        assert_eq!(o.transferred, 2);
        assert_eq!(o.suspects, vec!["b".to_string()]);
        assert_eq!(o.stderr, vec!["oops".to_string()]);
        assert!(!o.acceptable());
    }

    #[test]
    fn real_runner_deadline() {
        let mut r = RealRunner {
            rsync: "/bin/sh".into(),
        };
        let o = r.run(
            &["-c".into(), "sleep 30".into()],
            Some(Instant::now() + Duration::from_millis(300)),
        );
        assert_eq!(o.killed, Some(Killed::Deadline));
        assert!(!o.acceptable());
    }

    #[test]
    fn real_runner_missing_program() {
        let mut r = RealRunner {
            rsync: "/nonexistent/rsync".into(),
        };
        assert!(r.run(&[], None).spawn_error.is_some());
    }
}
