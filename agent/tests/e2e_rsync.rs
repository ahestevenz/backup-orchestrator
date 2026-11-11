// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

//! End to end: the real agent binary runs real rsync jobs. A stand-in `ssh`
//! on PATH hands each connection to the vendored `rrsync -wo`, exactly as the
//! server's sshd does with a locked push key (CLAUDE.md §5.9, §6.3).
//!
//! Needs rsync 3.x and python3. Skipped (with a message) when rsync 3 is
//! missing; set BN_TEST_RSYNC to point at one.

use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

fn rsync3() -> Option<PathBuf> {
    let candidates: Vec<PathBuf> = std::env::var("BN_TEST_RSYNC")
        .ok()
        .map(PathBuf::from)
        .into_iter()
        .chain(
            [
                "/opt/homebrew/bin/rsync",
                "/usr/local/bin/rsync",
                "/opt/local/bin/rsync",
                "/usr/bin/rsync",
            ]
            .map(PathBuf::from),
        )
        .collect();
    candidates.into_iter().find(|p| {
        Command::new(p)
            .arg("--version")
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).starts_with("rsync  version 3."))
            .unwrap_or(false)
    })
}

fn me() -> String {
    let out = Command::new("id").arg("-un").output().unwrap();
    String::from_utf8_lossy(&out.stdout).trim().to_string()
}

struct World {
    _dir: tempfile::TempDir,
    root: PathBuf,
    ah: PathBuf,
    server: PathBuf,
    rsync: PathBuf,
    path_env: String,
    user: String,
}

impl World {
    fn new(rsync: PathBuf) -> World {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let user = me();
        let ah = root.join("ah");
        let state = ah.join("users").join(&user).join("state");
        std::fs::create_dir_all(&state).unwrap();
        std::fs::write(state.join("id_ed25519"), "not used").unwrap();
        std::fs::write(ah.join("server_known_hosts"), "not used\n").unwrap();
        std::fs::write(
            ah.join("agent.toml"),
            format!(
                "server_host = \"server.home.lan\"\nserver_port = 22\nserver_user = \"{user}\"\n\
                 admin_user = \"{user}\"\nhost_name = \"athena\"\n"
            ),
        )
        .unwrap();
        // The staging folder a push key is locked to.
        let server = root.join("server/.staging/athena").join(&user);
        std::fs::create_dir_all(&server).unwrap();

        // rrsync, pointed at this rsync.
        let vendored =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../server/src/bn_backup/vendor/rrsync");
        let text = std::fs::read_to_string(vendored).unwrap().replace(
            "RSYNC = '/usr/bin/rsync'",
            &format!("RSYNC = '{}'", rsync.display()),
        );
        let rrsync = root.join("rrsync");
        std::fs::write(&rrsync, text).unwrap();

        // The stand-in ssh: drop ssh's options, run the remote command via rrsync.
        let bin = root.join("bin");
        std::fs::create_dir(&bin).unwrap();
        let ssh = bin.join("ssh");
        std::fs::write(
            &ssh,
            format!(
                "#!/bin/sh\n\
                 while [ $# -gt 0 ]; do case \"$1\" in -i|-o|-p|-l) shift 2;; -*) shift;; *) break;; esac; done\n\
                 shift\n\
                 SSH_ORIGINAL_COMMAND=\"$*\" exec python3 '{}' -wo '{}'\n",
                rrsync.display(),
                server.display()
            ),
        )
        .unwrap();
        std::fs::set_permissions(&ssh, std::fs::Permissions::from_mode(0o755)).unwrap();
        let path_env = format!(
            "{}:{}",
            bin.display(),
            std::env::var("PATH").unwrap_or_default()
        );
        World {
            _dir: dir,
            root,
            ah,
            server,
            rsync,
            path_env,
            user,
        }
    }

    fn src(&self, name: &str) -> PathBuf {
        let p = self.root.join("src").join(name);
        std::fs::create_dir_all(&p).unwrap();
        p
    }

    fn run(&self, job: serde_json::Value) -> serde_json::Value {
        let udir = self.ah.join("users").join(&self.user);
        std::fs::write(udir.join("job.json"), serde_json::to_vec(&job).unwrap()).unwrap();
        let out = Command::new(env!("CARGO_BIN_EXE_bn-backup-agent"))
            .args(["run", "--user", &self.user])
            .env("BN_BACKUP_AGENT_HOME", &self.ah)
            .env("BN_BACKUP_AGENT_RSYNC", &self.rsync)
            .env("PATH", &self.path_env)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "agent run failed: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let result = std::fs::read(udir.join("state/result.json")).unwrap();
        serde_json::from_slice(&result).unwrap()
    }

    fn job(&self, kind: &str, verify: bool, modules: serde_json::Value) -> serde_json::Value {
        serde_json::json!({
            "protocol": 1, "kind": kind, "job_id": "e2e", "run_id": "20261110-213000",
            "user": self.user, "host_name": "athena",
            "server": {"host": "server.home.lan", "port": 22, "user": self.user},
            "options": {"verify": verify, "partial": true, "dry_run": false, "io_timeout_seconds": 60},
            "timeout_seconds": 0,
            "modules": modules,
        })
    }
}

#[test]
fn backup_verify_and_probe_through_rrsync() {
    let Some(rsync) = rsync3() else {
        eprintln!("SKIPPED: rsync 3.x not found (set BN_TEST_RSYNC)");
        return;
    };
    let w = World::new(rsync);
    let photos = w.src("Photos");
    std::fs::create_dir(photos.join("2019")).unwrap();
    std::fs::write(photos.join("2019/DSC_0001.NEF"), b"raw-file-1").unwrap();
    // Whole seconds, like `touch -t` in spike S14.
    let when = std::time::UNIX_EPOCH + std::time::Duration::from_secs(1_577_836_800);
    let set_time = |p: &Path| {
        let f = std::fs::File::options().write(true).open(p).unwrap();
        f.set_modified(when).unwrap();
    };
    set_time(&photos.join("2019/DSC_0001.NEF"));
    std::fs::write(photos.join("2019/DSC_0002.NEF"), b"raw-file-2").unwrap();
    std::fs::write(photos.join("cache.tmp"), b"skip me").unwrap();
    let module = serde_json::json!([{
        "name": "photos", "type": "path",
        "src_path": photos.to_string_lossy(), "excludes": ["*.tmp"]
    }]);

    // 1. A real backup into the locked staging folder.
    let r = w.run(w.job("backup", false, module.clone()));
    assert_eq!(r["state"], "done", "{r:#}");
    let m = &r["modules"][0];
    assert_eq!(m["status"], "ok", "{r:#}");
    assert_eq!(m["files_transferred"], 2, "{r:#}");
    let staged = w.server.join("photos/Photos/2019/DSC_0001.NEF");
    assert_eq!(std::fs::read(&staged).unwrap(), b"raw-file-1");
    assert!(!w.server.join("photos/Photos/cache.tmp").exists());

    // 2. --delete: a file removed at the source disappears from staging.
    std::fs::remove_file(photos.join("2019/DSC_0002.NEF")).unwrap();
    let r = w.run(w.job("backup", false, module.clone()));
    assert_eq!(r["modules"][0]["status"], "ok", "{r:#}");
    assert!(!w.server.join("photos/Photos/2019/DSC_0002.NEF").exists());

    // 3. The verify pass finds a silent change and overwrites nothing (D-50).
    let f = photos.join("2019/DSC_0001.NEF");
    std::fs::write(&f, b"RAW-FILE-1").unwrap(); // same size, different content
    set_time(&f); // same date
    let r = w.run(w.job("backup", true, module.clone()));
    let m = &r["modules"][0];
    assert_eq!(m["status"], "ok", "{r:#}");
    assert_eq!(m["suspect_count"], 1, "{r:#}");
    assert_eq!(m["suspect_files"][0], "Photos/2019/DSC_0001.NEF");
    assert_eq!(
        std::fs::read(&staged).unwrap(),
        b"raw-file-1",
        "nothing overwritten"
    );

    // 4. A probe: module check plus a real write into .probe/.
    let mut modules = module.as_array().unwrap().clone();
    modules.push(serde_json::json!({
        "name": "gone", "type": "path", "src_path": w.root.join("nope").to_string_lossy()
    }));
    let r = w.run(w.job("probe", false, serde_json::Value::Array(modules)));
    assert_eq!(r["server_reachable"], true, "{r:#}");
    assert_eq!(r["modules"][0]["status"], "ok");
    assert_eq!(r["modules"][1]["error_kind"], "missing");
    assert!(w.server.join(".probe/probe").exists());
}

#[test]
fn rrsync_refusal_is_server_denied() {
    let Some(rsync) = rsync3() else {
        eprintln!("SKIPPED: rsync 3.x not found (set BN_TEST_RSYNC)");
        return;
    };
    let w = World::new(rsync);
    let src = w.src("Docs");
    std::fs::write(src.join("a.txt"), b"a").unwrap();
    // The staging folder is not writable: like a server that refuses the write.
    std::fs::set_permissions(&w.server, std::fs::Permissions::from_mode(0o500)).unwrap();
    let module =
        serde_json::json!([{"name": "docs", "type": "path", "src_path": src.to_string_lossy()}]);
    let r = w.run(w.job("backup", false, module));
    std::fs::set_permissions(&w.server, std::fs::Permissions::from_mode(0o700)).unwrap();
    let m = &r["modules"][0];
    assert_eq!(m["status"], "failed", "{r:#}");
    assert_eq!(m["error_kind"], "server_denied", "{r:#}");
}
