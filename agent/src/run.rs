// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! `run --user <user>`: execute the current job as that user (CLAUDE.md §5.3).
//! Started only by launchd or systemd, never over SSH (D-05).

use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;
use std::time::{Duration, Instant};

use nix::unistd::{geteuid, User};

use crate::awake::KeepAwake;
use crate::classify::{classify, message};
use crate::job::{Job, JobKind, ModuleJob, ModuleType};
use crate::paths::{rsync_path, AgentConfig, Layout, Os};
use crate::probe::{self, Mounts, SystemMounts};
use crate::result::{ErrorKind, JobResult, ModuleResult, State, Status};
use crate::rsync::{self, Common, Killed, Outcome, RealRunner, Runner, Target, STOP};
use crate::util::{atomic_write, now_rfc3339};

const PROBE_TIMEOUT: Duration = Duration::from_secs(120);
const HOST_FILES: [&str; 2] = ["/etc/hosts", "/etc/motd"];

/// What a job needs from its surroundings; tests provide fakes.
pub struct Env<'a> {
    pub os: Os,
    pub layout: &'a Layout,
    pub cfg: &'a AgentConfig,
    /// The user's home folder.
    pub home: PathBuf,
    pub mounts: &'a dyn Mounts,
    pub now: &'a dyn Fn() -> String,
    /// Where the probe creates its small test folder.
    pub tmp_dir: PathBuf,
}

impl Env<'_> {
    fn target(&self, user: &str) -> Target {
        Target {
            user: self.cfg.server_user.clone(),
            host: self.cfg.server_host.clone(),
            port: self.cfg.server_port,
            key: self.layout.key(user),
            known_hosts: self.layout.known_hosts(),
        }
    }
}

extern "C" fn on_signal(_: libc::c_int) {
    STOP.store(true, Ordering::SeqCst);
}

fn install_signal_handlers() {
    use nix::sys::signal::{sigaction, SaFlags, SigAction, SigHandler, SigSet, Signal};
    let action = SigAction::new(
        SigHandler::Handler(on_signal),
        SaFlags::empty(),
        SigSet::empty(),
    );
    for sig in [Signal::SIGTERM, Signal::SIGINT, Signal::SIGHUP] {
        // SAFETY: the handler only stores to an atomic, which is async-signal-safe.
        let _ = unsafe { sigaction(sig, &action) };
    }
}

pub fn main(user: &str) -> i32 {
    let me = User::from_uid(geteuid()).ok().flatten().map(|u| u.name);
    if me.as_deref() != Some(user) {
        eprintln!(
            "run must be started by launchd or systemd as {user} (running as {})",
            me.unwrap_or_else(|| "?".into())
        );
        return 2;
    }
    install_signal_handlers();
    let layout = Layout::system();
    let cfg = match layout.load_config() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{}", e.message);
            return 1;
        }
    };
    let job = match std::fs::read(layout.job_json(user)) {
        Ok(bytes) => match Job::parse(&bytes) {
            Ok(j) if j.user == user => j,
            Ok(j) => {
                eprintln!("job.json is for {}, not {user}", j.user);
                return 1;
            }
            Err(e) => {
                eprintln!("{}", e.message);
                return 1;
            }
        },
        Err(e) => {
            eprintln!("no job to run: {e}");
            return 1;
        }
    };
    let home = User::from_name(user)
        .ok()
        .flatten()
        .map(|u| u.dir)
        .unwrap_or_else(|| PathBuf::from("/nonexistent"));
    let os = Os::current();
    let mut notes = Vec::new();
    let _awake = KeepAwake::start(os, &mut notes);
    let mounts = SystemMounts::load();
    let env = Env {
        os,
        layout: &layout,
        cfg: &cfg,
        home,
        mounts: &mounts,
        now: &now_rfc3339,
        tmp_dir: std::env::temp_dir(),
    };
    let result_path = layout.result_json(user);
    let mut save = |r: &JobResult| {
        if let Ok(text) = serde_json::to_vec_pretty(r) {
            if let Err(e) = atomic_write(&result_path, &text, 0o600, None) {
                eprintln!("cannot write {}: {e}", result_path.display());
            }
        }
    };
    let mut runner = RealRunner {
        rsync: rsync_path(),
    };
    execute(&env, &job, &mut runner, notes, &mut save);
    0
}

/// Run a job and return its final result. `save` is called whenever the result changes.
pub fn execute(
    env: &Env,
    job: &Job,
    runner: &mut dyn Runner,
    notes: Vec<String>,
    save: &mut dyn FnMut(&JobResult),
) -> JobResult {
    let mut r = JobResult::start(job, (env.now)(), probe::fda(env.os));
    r.notes = notes;
    save(&r);
    let deadline = (job.timeout_seconds > 0)
        .then(|| Instant::now() + Duration::from_secs(job.timeout_seconds));
    match job.kind {
        JobKind::Probe => probe_job(env, job, runner, &mut r),
        JobKind::Backup => backup_job(env, job, runner, deadline, &mut r, save),
    }
    r.state = State::Done;
    r.finished_at = Some((env.now)());
    save(&r);
    r
}

fn probe_job(env: &Env, job: &Job, runner: &mut dyn Runner, r: &mut JobResult) {
    for m in &job.modules {
        r.modules.push(
            match probe::check_module(m, &env.home, env.os, env.mounts) {
                Ok(()) => ModuleResult::ok(&m.name),
                Err((kind, msg)) => ModuleResult::failed(&m.name, kind, msg),
            },
        );
    }
    // A real write to the server, so a server that refuses writes is caught.
    let dir = env
        .tmp_dir
        .join(format!("bn-backup-probe-{}", std::process::id()));
    let made = std::fs::create_dir_all(&dir)
        .and_then(|_| std::fs::write(dir.join("probe"), format!("{}\n", (env.now)())));
    if let Err(e) = made {
        r.server_reachable = Some(false);
        r.server_error = Some(format!("cannot create the probe folder: {e}"));
        r.server_error_kind = Some("network".into());
        return;
    }
    let opts = Common {
        io_timeout_seconds: job.options.io_timeout_seconds.min(PROBE_TIMEOUT.as_secs()),
        partial: false,
        dry_run: false,
    };
    let log = env.layout.state_dir(&job.user).join("rsync-probe.log");
    let args = rsync::probe_args(&env.target(&job.user), &opts, &log, &dir);
    let out = runner.run(&args, Some(Instant::now() + PROBE_TIMEOUT));
    let _ = std::fs::remove_dir_all(&dir);
    if out.acceptable() {
        r.server_reachable = Some(true);
        return;
    }
    r.server_reachable = Some(false);
    let last = out
        .spawn_error
        .clone()
        .or_else(|| {
            out.stderr
                .iter()
                .rev()
                .find(|l| !l.trim().is_empty())
                .cloned()
        })
        .unwrap_or_else(|| format!("rsync exit {:?}", out.exit));
    r.server_error = Some(last);
    let (_, kind) = classify(out.exit, &out.stderr, env.os);
    r.server_error_kind = Some(
        if kind == Some(ErrorKind::ServerDenied) {
            "server_denied"
        } else {
            "network"
        }
        .into(),
    );
}

fn backup_job(
    env: &Env,
    job: &Job,
    runner: &mut dyn Runner,
    deadline: Option<Instant>,
    r: &mut JobResult,
    save: &mut dyn FnMut(&JobResult),
) {
    let opts = Common {
        io_timeout_seconds: job.options.io_timeout_seconds,
        partial: job.options.partial,
        dry_run: job.options.dry_run,
    };
    let mut drive_gone = false;
    for m in &job.modules {
        let res = if drive_gone {
            ModuleResult::failed(
                &m.name,
                ErrorKind::Skipped,
                "not run: an external drive was disconnected during this job",
            )
        } else if STOP.load(Ordering::SeqCst) {
            ModuleResult::failed(&m.name, ErrorKind::Other, "stopped by the server")
        } else if deadline.is_some_and(|d| Instant::now() >= d) {
            ModuleResult::failed(
                &m.name,
                ErrorKind::Timeout,
                "the job ran longer than its time limit",
            )
        } else {
            match m.kind {
                ModuleType::Path => path_module(env, job, m, &opts, runner, deadline, &mut r.notes),
                ModuleType::HostConfig => {
                    host_config_module(env, job, m, &opts, runner, deadline, &mut r.notes)
                }
            }
        };
        // D-46: a vanished drive ends the job; the server aborts the whole run.
        if res.error_kind == Some(ErrorKind::DriveMissing) {
            drive_gone = true;
        }
        r.modules.push(res);
        save(r);
    }
}

fn outcome_result(name: &str, out: &Outcome, os: Os) -> ModuleResult {
    if let Some(e) = &out.spawn_error {
        return ModuleResult::failed(name, ErrorKind::Other, e.clone());
    }
    match out.killed {
        Some(Killed::Deadline) => {
            let mut m = ModuleResult::failed(
                name,
                ErrorKind::Timeout,
                "the job ran longer than its time limit",
            );
            m.rsync_exit = out.exit;
            return m;
        }
        Some(Killed::Stopped) => {
            return ModuleResult::failed(name, ErrorKind::Other, "stopped by the server");
        }
        None => {}
    }
    let (status, kind) = classify(out.exit, &out.stderr, os);
    ModuleResult {
        name: name.to_string(),
        status,
        rsync_exit: out.exit,
        error_kind: kind,
        message: message(&out.stderr),
        files_transferred: out.transferred,
        ..ModuleResult::ok(name)
    }
}

fn log_len(p: &Path) -> u64 {
    std::fs::metadata(p).map(|m| m.len()).unwrap_or(0)
}

fn log_since(p: &Path, offset: u64) -> String {
    std::fs::read(p)
        .map(|b| String::from_utf8_lossy(b.get(offset as usize..).unwrap_or(&[])).into_owned())
        .unwrap_or_default()
}

fn path_module(
    env: &Env,
    job: &Job,
    m: &ModuleJob,
    opts: &Common,
    runner: &mut dyn Runner,
    deadline: Option<Instant>,
    notes: &mut Vec<String>,
) -> ModuleResult {
    let src = m.src_path.as_deref().unwrap_or_default();
    if let Err((kind, msg)) = probe::check_module(m, &env.home, env.os, env.mounts) {
        return ModuleResult::failed(&m.name, kind, msg);
    }
    let target = env.target(&job.user);
    let log = env.layout.rsync_log(&job.user, &m.name);
    let before = log_len(&log);
    let args = rsync::path_module_args(&target, opts, &log, &m.name, src, &m.excludes);
    let out = runner.run(&args, deadline);
    let mut res = outcome_result(&m.name, &out, env.os);
    res.bytes_transferred = rsync::sent_bytes(&log_since(&log, before));

    // Did the drive vanish during the transfer? (§5.3 step 4, D-46)
    if res.status == Status::Failed
        && probe::external_drive_mounted(src, env.os, env.mounts).is_some()
    {
        if let Err((ErrorKind::DriveMissing, msg)) =
            probe::check_module(m, &env.home, env.os, env.mounts)
        {
            res.error_kind = Some(ErrorKind::DriveMissing);
            res.message = format!("{msg} (it disappeared during the backup)");
        }
    }

    // D-50: report-only verify pass, never in a dry run.
    if res.status == Status::Ok && job.options.verify && !job.options.dry_run {
        let vlog = env.layout.verify_log(&job.user, &m.name);
        let vargs = rsync::verify_args(&target, opts, &vlog, &m.name, src, &m.excludes);
        let v = runner.run(&vargs, deadline);
        if v.acceptable() {
            res.suspect_count = v.suspect_count;
            res.suspect_files = v.suspects;
        } else {
            let why = v
                .spawn_error
                .clone()
                .or_else(|| v.stderr.last().cloned())
                .unwrap_or_else(|| format!("rsync exit {:?}", v.exit));
            notes.push(format!("verify failed: {}: {why}", m.name));
        }
    }
    res
}

fn host_config_module(
    env: &Env,
    job: &Job,
    m: &ModuleJob,
    opts: &Common,
    runner: &mut dyn Runner,
    deadline: Option<Instant>,
    notes: &mut Vec<String>,
) -> ModuleResult {
    if let Err((kind, msg)) = probe::check_module(m, &env.home, env.os, env.mounts) {
        return ModuleResult::failed(&m.name, kind, msg);
    }
    let target = env.target(&job.user);
    let log = env.layout.rsync_log(&job.user, &m.name);
    let before = log_len(&log);
    let files: Vec<String> = HOST_FILES
        .iter()
        .filter(|f| {
            let exists = Path::new(f).exists();
            if !exists {
                notes.push(format!(
                    "{}: {f} does not exist on this host; skipped",
                    m.name
                ));
            }
            exists
        })
        .map(|f| f.to_string())
        .collect();
    let mut outcomes = Vec::new();
    if !files.is_empty() {
        outcomes.push(runner.run(
            &rsync::host_files_args(&target, opts, &log, &m.name, &files),
            deadline,
        ));
    }
    if outcomes.iter().all(Outcome::acceptable) {
        outcomes.push(runner.run(
            &rsync::dotfiles_args(&target, opts, &log, &m.name, &job.user, &env.home),
            deadline,
        ));
    }
    let transferred = outcomes.iter().map(|o| o.transferred).sum();
    let worst = outcomes
        .iter()
        .find(|o| !o.acceptable())
        .or(outcomes.last())
        .expect("at least one transfer");
    let mut res = outcome_result(&m.name, worst, env.os);
    res.files_transferred = transferred;
    res.bytes_transferred = rsync::sent_bytes(&log_since(&log, before));
    res
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::job::tests::{cfg, job};
    use crate::result::Fda;
    use std::collections::VecDeque;

    struct FakeMounts(Vec<PathBuf>);
    impl Mounts for FakeMounts {
        fn is_mount_point(&self, p: &Path) -> bool {
            self.0.iter().any(|x| x == p)
        }
    }

    /// Returns scripted outcomes and records every command line.
    #[derive(Default)]
    struct FakeRunner {
        script: VecDeque<Outcome>,
        calls: Vec<Vec<String>>,
    }
    impl Runner for FakeRunner {
        fn run(&mut self, args: &[String], _deadline: Option<Instant>) -> Outcome {
            self.calls.push(args.to_vec());
            self.script.pop_front().unwrap_or(Outcome {
                exit: Some(0),
                ..Outcome::default()
            })
        }
    }

    fn ok(n: u64) -> Outcome {
        Outcome {
            exit: Some(0),
            transferred: n,
            ..Outcome::default()
        }
    }

    fn exit(code: i32, err: &str) -> Outcome {
        Outcome {
            exit: Some(code),
            stderr: vec![err.into()],
            ..Outcome::default()
        }
    }

    struct World {
        dir: tempfile::TempDir,
        layout: Layout,
    }

    impl World {
        fn new() -> World {
            let dir = tempfile::tempdir().unwrap();
            let layout = Layout {
                home: dir.path().join("ah"),
            };
            std::fs::create_dir_all(layout.state_dir("sofia")).unwrap();
            std::fs::create_dir_all(dir.path().join("home")).unwrap();
            World { dir, layout }
        }
        fn src(&self, name: &str, files: &[&str]) -> String {
            let p = self.dir.path().join(name);
            std::fs::create_dir_all(&p).unwrap();
            for f in files {
                std::fs::write(p.join(f), b"x").unwrap();
            }
            p.to_string_lossy().into_owned()
        }
    }

    fn run_job(w: &World, j: &Job, runner: &mut FakeRunner, mounts: &FakeMounts) -> JobResult {
        let c = cfg();
        let now = || "2026-11-10T10:30:00Z".to_string();
        let env = Env {
            os: Os::Linux,
            layout: &w.layout,
            cfg: &c,
            home: w.dir.path().join("home"),
            mounts,
            now: &now,
            tmp_dir: w.dir.path().join("tmp"),
        };
        let mut saves = 0;
        let r = execute(&env, j, runner, vec![], &mut |_| saves += 1);
        assert!(saves >= 2);
        r
    }

    fn path_job(w: &World, modules: Vec<(&str, String)>) -> Job {
        let mut j = job();
        j.modules = modules
            .into_iter()
            .map(|(name, src)| ModuleJob {
                name: name.into(),
                kind: ModuleType::Path,
                src_path: Some(src),
                excludes: vec![],
                expect_nonempty: false,
            })
            .collect();
        let _ = w;
        j
    }

    #[test]
    fn all_modules_ok() {
        let w = World::new();
        let j = path_job(
            &w,
            vec![("a", w.src("A", &["1"])), ("b", w.src("B", &["2"]))],
        );
        let mut r = FakeRunner {
            script: VecDeque::from([ok(3), ok(1)]),
            ..Default::default()
        };
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.state, State::Done);
        assert_eq!(res.fda, Fda::NotApplicable);
        assert!(res.modules.iter().all(|m| m.status == Status::Ok));
        assert_eq!(res.modules[0].files_transferred, 3);
        assert_eq!(r.calls.len(), 2);
    }

    #[test]
    fn one_failure_does_not_stop_the_next() {
        let w = World::new();
        let j = path_job(
            &w,
            vec![("a", w.src("A", &["1"])), ("b", w.src("B", &["2"]))],
        );
        let mut r = FakeRunner {
            script: VecDeque::from([
                exit(
                    23,
                    "rsync: [sender] opendir \"x\" failed: Permission denied (13)",
                ),
                ok(1),
            ]),
            ..Default::default()
        };
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.modules[0].error_kind, Some(ErrorKind::Permission));
        assert_eq!(res.modules[0].rsync_exit, Some(23));
        assert_eq!(res.modules[1].status, Status::Ok);
    }

    #[test]
    fn missing_source_skips_rsync() {
        let w = World::new();
        let j = path_job(&w, vec![("a", "/nonexistent/bn-backup/x".into())]);
        let mut r = FakeRunner::default();
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.modules[0].error_kind, Some(ErrorKind::Missing));
        assert_eq!(res.modules[0].rsync_exit, None);
        assert!(r.calls.is_empty());
    }

    #[test]
    fn drive_missing_stops_the_job() {
        let w = World::new();
        let j = path_job(
            &w,
            vec![
                ("a", w.src("A", &["1"])),
                ("photos", "/mnt/photos/Photos".into()),
                ("c", w.src("C", &["3"])),
                ("d", w.src("D", &["4"])),
            ],
        );
        let mut r = FakeRunner::default();
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        let kinds: Vec<Option<ErrorKind>> = res.modules.iter().map(|m| m.error_kind).collect();
        assert_eq!(
            kinds,
            [
                None,
                Some(ErrorKind::DriveMissing),
                Some(ErrorKind::Skipped),
                Some(ErrorKind::Skipped)
            ]
        );
        assert_eq!(r.calls.len(), 1, "no rsync after the drive went missing");
    }

    #[test]
    fn drive_vanishing_during_transfer_is_detected() {
        // Mounted at the pre-check, gone when rsync fails.
        use std::cell::RefCell;
        use std::rc::Rc;
        struct Toggle(Rc<RefCell<bool>>);
        impl Mounts for Toggle {
            fn is_mount_point(&self, p: &Path) -> bool {
                *self.0.borrow() && p == Path::new("/mnt/photos")
            }
        }
        let w = World::new();
        let mounted = Rc::new(RefCell::new(true));
        let mounts = Toggle(mounted.clone());
        // The source must exist for the pre-check; use a real folder under a fake /mnt root
        // by checking the classification path directly.
        let src = w.src("P", &["1"]);
        let m = ModuleJob {
            name: "photos".into(),
            kind: ModuleType::Path,
            src_path: Some("/mnt/photos/Photos".into()),
            excludes: vec![],
            expect_nonempty: false,
        };
        assert!(probe::check_module(&m, Path::new(&src), Os::Linux, &mounts).is_err());
        *mounted.borrow_mut() = false;
        let err = probe::check_module(&m, Path::new(&src), Os::Linux, &mounts).unwrap_err();
        assert_eq!(err.0, ErrorKind::DriveMissing);
    }

    #[test]
    fn source_empty_when_backup_holds_data() {
        let w = World::new();
        let mut j = path_job(&w, vec![("a", w.src("A", &[]))]);
        j.modules[0].expect_nonempty = true;
        let mut r = FakeRunner::default();
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.modules[0].error_kind, Some(ErrorKind::SourceEmpty));
        assert!(r.calls.is_empty());
    }

    #[test]
    fn timeout_marks_current_and_remaining() {
        let w = World::new();
        let mut j = path_job(
            &w,
            vec![("a", w.src("A", &["1"])), ("b", w.src("B", &["2"]))],
        );
        j.timeout_seconds = 3600;
        let mut r = FakeRunner {
            script: VecDeque::from([Outcome {
                killed: Some(Killed::Deadline),
                ..Outcome::default()
            }]),
            ..Default::default()
        };
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.modules[0].error_kind, Some(ErrorKind::Timeout));
        // The deadline has not really passed in this test, so b runs; the
        // runner-level deadline is covered in rsync.rs.
        assert_eq!(res.modules.len(), 2);
    }

    #[test]
    fn verify_pass_reports_suspects_and_keeps_ok() {
        let w = World::new();
        let mut j = path_job(&w, vec![("a", w.src("A", &["1"]))]);
        j.options.verify = true;
        let mut r = FakeRunner {
            script: VecDeque::from([
                ok(0),
                Outcome {
                    exit: Some(0),
                    suspect_count: 2,
                    suspects: vec!["A/x.NEF".into(), "A/y.NEF".into()],
                    ..Outcome::default()
                },
            ]),
            ..Default::default()
        };
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.modules[0].status, Status::Ok);
        assert_eq!(res.modules[0].suspect_count, 2);
        assert_eq!(r.calls.len(), 2);
        assert!(r.calls[1].contains(&"--checksum".to_string()));
        assert!(!r.calls[0].contains(&"--checksum".to_string()));
    }

    #[test]
    fn verify_failure_is_a_note_not_a_failure() {
        let w = World::new();
        let mut j = path_job(&w, vec![("a", w.src("A", &["1"]))]);
        j.options.verify = true;
        let mut r = FakeRunner {
            script: VecDeque::from([ok(0), exit(12, "protocol error")]),
            ..Default::default()
        };
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.modules[0].status, Status::Ok);
        assert!(res.notes.iter().any(|n| n.starts_with("verify failed: a:")));
    }

    #[test]
    fn no_verify_in_dry_run() {
        let w = World::new();
        let mut j = path_job(&w, vec![("a", w.src("A", &["1"]))]);
        j.options.verify = true;
        j.options.dry_run = true;
        let mut r = FakeRunner::default();
        run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(r.calls.len(), 1);
        assert!(r.calls[0].contains(&"--dry-run".to_string()));
    }

    #[test]
    fn host_config_runs_two_transfers() {
        let w = World::new();
        let mut j = job();
        j.modules = vec![ModuleJob {
            name: "sofia-athena".into(),
            kind: ModuleType::HostConfig,
            src_path: None,
            excludes: vec![],
            expect_nonempty: false,
        }];
        let mut r = FakeRunner::default();
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.modules[0].status, Status::Ok);
        let last = r.calls.last().unwrap();
        assert!(last.contains(&"--include=/.*".to_string()));
        assert!(last.last().unwrap().ends_with("sofia-athena/sofia/"));
        if Path::new("/etc/hosts").exists() {
            assert_eq!(r.calls.len(), 2);
            assert!(!r.calls[0].contains(&"--delete".to_string()));
        }
    }

    #[test]
    fn probe_job_reports_modules_and_server() {
        let w = World::new();
        let mut j = path_job(
            &w,
            vec![("a", w.src("A", &["1"])), ("b", "/nonexistent/x".into())],
        );
        j.kind = JobKind::Probe;
        let mut r = FakeRunner {
            script: VecDeque::from([exit(
                23,
                "rsync: [receiver] mkstemp failed: Operation not permitted (1)",
            )]),
            ..Default::default()
        };
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.modules[0].status, Status::Ok);
        assert_eq!(res.modules[1].error_kind, Some(ErrorKind::Missing));
        assert_eq!(res.server_reachable, Some(false));
        assert_eq!(res.server_error_kind.as_deref(), Some("server_denied"));
        assert_eq!(r.calls.len(), 1);
        assert!(r.calls[0].last().unwrap().ends_with(":.probe/"));
        assert!(!w
            .dir
            .path()
            .join("tmp")
            .join(format!("bn-backup-probe-{}", std::process::id()))
            .exists());
    }

    #[test]
    fn probe_job_server_ok() {
        let w = World::new();
        let mut j = path_job(&w, vec![("a", w.src("A", &["1"]))]);
        j.kind = JobKind::Probe;
        let mut r = FakeRunner::default();
        let res = run_job(&w, &j, &mut r, &FakeMounts(vec![]));
        assert_eq!(res.server_reachable, Some(true));
        assert_eq!(res.server_error, None);
    }
}
