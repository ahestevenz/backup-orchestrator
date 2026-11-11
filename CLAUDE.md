# CLAUDE.md — bleiben Backup Orchestrator v2

Instructions for an AI agent implementing **bleiben Backup Orchestrator v2** in this repository.

**What it is for (D-37).** Backup Orchestrator started in 2018 to keep a
photographer's work safe. v2 is a *local* backup system aimed first at
photographers (large RAW/video archives, catalogs, external drives) and open
to anyone who wants a local backup at home. Keep that audience in mind in every
user-facing message, example and default: examples use photo archives,
messages assume a non-specialist reader.

**Where it lives (D-36).** The product belongs to the **bleiben** brand. The
repository is `github.com/bleiben-labs/backup-orchestrator`, and releases are
published there. The owner transfers the existing repository from
`ahestevenz/backup-orchestrator` to the `bleiben-labs` organization (GitHub
transfer, keeping history and redirects). Before you start, check `git remote -v`.
If the repository is not yet under `bleiben-labs`, stop and ask the owner to
transfer it. Do not create a new repository and do not copy history by hand.

**License (D-41…D-44).** PolyForm Noncommercial 1.0.0, copyright Ariel Hernandez (bleiben). See
§13 for every licensing file you must create and the rules that follow from it.

The full design, with explanations and the reasoning behind each choice, is in
[`docs/design.md`](docs/design.md). Read it before starting. **This file is the
binding specification.** Where this file is more specific than the design doc,
follow this file. Decision IDs (`D-01` … `D-57`) refer to the decision log in
section 18 of the design doc.

---

## 0. Rules of engagement

1. **Do not invent decisions.** Everything below has been decided with the
   owner. If you hit a question this file and `docs/design.md` do not answer,
   **stop and ask the owner**. Do not pick a default yourself. Write the open
   question in `docs/open-questions.md` and ask it.
2. **Phase 0 spikes gate everything.** If any spike in §11 produces a result
   that contradicts this file, stop and report it before writing more code.
3. **Branching (D-47).** Never push to `main` directly. Changes reach `main`
   only through two pull requests that the owner merges: the licensing PR
   (Phase L, §11), opened first from a branch `licensing` cut from `main`, and
   the final `v2` → `main` PR (Phase 8). All other work happens on branch `v2`,
   created from `main` *after* the licensing PR is merged: one pull request per
   phase, targeting `v2`.
4. **v1 stays runnable on `main` until Phase 8.** On `v2` the v1 package is
   replaced. Do not keep `bn-run-backup` (D-10). Server and agent reach `main`
   together, in the single Phase 8 merge.
5. **Commits:** small and focused, imperative subject line, body explains why.
   Never commit secrets, real phone numbers, emails or host names. Examples use
   `example.com`, `+61400000000`, `galactica.home.lan`, `athena.home.lan` and
   `columbia.home.lan`.
6. **Tests are part of done.** Each phase lists acceptance criteria. A phase is
   finished only when they pass in CI.
7. **Language:** code and identifiers in English; user-facing messages short
   and actionable (say what failed and what to do next).

---

## 1. What you are building

Two programs and their packaging:

| Component | Language | Runs on | Binary / command |
|---|---|---|---|
| **Server** | Python ≥ 3.11 | Any always-on Mac (macOS 13+) or Debian-based Linux computer, as the operator's own admin account (§6.1) | `bn-backup` |
| **Agent** | Rust (stable, edition 2021) | Every source host: macOS 13+ (Apple silicon + Intel), Debian-based Linux (amd64, arm64) | `bn-backup-agent` |

- The server decides everything. The agent only executes jobs (D-01).
- Data is **pushed** by the agent to the server with rsync over SSH (D-04).
- The server starts agent jobs over SSH with the agent's `ctl start <user>`
  command (through a locked control key, §5.11), which asks **launchd** (macOS) or
  **systemd** (Linux) to start the job. The server **never** runs `bn-backup-agent run`
  directly over SSH (D-05). This keeps the macOS Full Disk Access grant
  effective: the TCC "responsible process" must be the agent, not `sshd`.

---

## 2. Repository layout (monorepo, D-10)

```
/
├── CLAUDE.md
├── README.md                      rewritten for v2 (Phase 7)
├── LICENSE                        PolyForm Noncommercial 1.0.0 (§13)
├── LICENSING.md                   plain-language licensing policy (§13)
├── TRADEMARKS.md                  bleiben name and logo (§13)
├── THIRD_PARTY_NOTICES.md         rsync, rrsync, libraries (§13)
├── CONTRIBUTING.md                how to contribute + CLA requirement (§13)
├── CLA.md                         contributor licence agreement text (§13)
├── docs/
│   ├── design.md                  the design (do not edit without owner approval)
│   ├── spikes.md                  Phase 0 results
│   ├── open-questions.md          anything you had to ask
│   └── testing-macos.md           manual macOS test checklist (Phase 6)
├── server/
│   ├── pyproject.toml             project name "bn-backup", import package "bn_backup"
│   ├── src/bn_backup/
│   │   ├── __init__.py            __version__
│   │   ├── cli.py                 argparse entry point (main)
│   │   ├── config.py              pydantic models + loader + validation + migrate + show
│   │   ├── config_edit.py         round-trip YAML edits for `hosts add` (ruamel.yaml)
│   │   ├── paths.py               backup_directory sub-paths
│   │   ├── state.py               run.json / hosts / history / lock models + IO
│   │   ├── ssh.py                 OpenSSH subprocess transport
│   │   ├── agentctl.py            typed wrappers for every `ctl` command
│   │   ├── keys.py                managed authorized_keys block
│   │   ├── hosts.py               hosts add / list / bootstrap / configure / remove / forget
│   │   ├── status.py              the board (status, server status, agent status)
│   │   ├── runs.py                runs list / show / cancel
│   │   ├── runner.py              the run algorithm
│   │   ├── clone.py               APFS clonefile / reflink
│   │   ├── promotion.py           journaled promotion
│   │   ├── report.py              backup_report.log + history + hints
│   │   ├── wake.py                Wake-on-LAN sender
│   │   ├── notify/__init__.py, email.py, signal.py
│   │   ├── schedule.py            launchd plist / systemd timer for scheduled runs
│   │   ├── releases.py            download + verify agent packages
│   │   ├── server_init.py         `server init`
│   │   ├── clock.py               injectable clock (tests)
│   │   └── vendor/rrsync          upstream rrsync from rsync 3.4.1 + COPYING
│   └── tests/
├── agent/
│   ├── Cargo.toml                 package "bn-backup-agent"
│   ├── src/
│   │   ├── main.rs                clap: `ctl …` and `run`
│   │   ├── paths.rs  job.rs  result.rs  rsync.rs  classify.rs
│   │   ├── probe.rs  run.rs  awake.rs  wol.rs  sudoers.rs  info.rs
│   │   ├── ctl/{setup,ping,info,user,submit,start,stop,result,log,fda,dispatch,uninstall}.rs
│   │   └── platform/{macos.rs, linux.rs}
│   ├── tests/
│   └── packaging/
│       ├── macos/ Info.plist, launchd.plist.tmpl, scripts/postinstall, build-pkg.sh
│       └── linux/ bn-backup-agent@.service, postinst, prerm (cargo-deb metadata in Cargo.toml)
├── packaging/rsync/
│   ├── VERSION                    3.4.1
│   ├── SHA256                     pinned tarball checksum
│   └── build-macos-universal.sh
├── tests/integration/             docker compose: 1 server + 2 Debian hosts
└── .github/workflows/
    ├── ci.yml                     on push/PR
    ├── cla.yml                    contributor agreement check (§13)
    └── release.yml                on tag v*
```

Delete v1's `setup.py`, `requirements.txt`, `MANIFEST.in`, `src/backup_orchestrator/`
and `.pylintrc` once their useful parts are ported (§10). Keep
`.pre-commit-config.yaml`, updated for ruff + cargo fmt.

---

## 3. Tooling

**Python (server):** uv for envs/builds, `ruff` (lint + format), `mypy --strict`
on `src/`, `pytest`. Runtime dependencies only: `pydantic>=2,<3`, `pyyaml`,
`loguru`, `ruamel.yaml` (only for `hosts add`, to edit the config while keeping
comments and layout; all other reading uses pyyaml). Use `argparse` for the CLI. Use `subprocess` for ssh/scp/rsync and
stdlib `smtplib` for email. No paramiko. No other runtime dependencies without
asking.

**Rust (agent):** crates `clap` (derive), `serde`, `serde_json`, `toml`,
`anyhow`, `thiserror`, `nix` (users, signals, uid/gid), `time` (RFC 3339 UTC),
`libc`, `shell-words` (§5.11). No async runtime. Run `cargo fmt` and `cargo clippy -D warnings`.
Linux builds are static musl (`x86_64-unknown-linux-musl`,
`aarch64-unknown-linux-musl`). macOS builds are universal (`lipo` of
`aarch64-apple-darwin` + `x86_64-apple-darwin`), deployment target 13.0.

**Versions:** one release version for everything, starting at `2.0.0`. It goes
in `server/pyproject.toml`, `bn_backup.__version__` and `agent/Cargo.toml`, and
CI checks they match the tag. Agent **protocol** is an integer, starting at
`1`. The server accepts agents whose `[protocol_min, protocol_max]` includes
`SERVER_PROTOCOL = 1`.

---

## 4. Configuration (D-11)

YAML (D-31), default path `~/.config/bn-backup/config.yml` in the operator's
home (§6.1), overridable with the global option `-c/--config PATH`. Mode 0600
in a directory 0700. The operator edits it with any editor, and `hosts add`
writes it (atomically: temp file in the same directory + rename, keeping the
mode). It holds no secrets. Pydantic models with
`model_config = ConfigDict(extra="forbid")` everywhere.

```yaml
version: 2                                   # required, must be 2

server:
  backup_directory: /Volumes/Backup/bn-backup   # required, absolute
  ssh_host: server.home.lan                    # required: FQDN, .local name or IP
  ssh_port: 22                                  # default 22
  receive_user: ariel                           # required: the operator's account on the server (§6.1)

settings:                                    # every key optional, defaults shown
  mode: mirror                               # mirror | snapshot
  snapshot_keep: 8                           # int >= 1
  verify_backup: false                       # report-only verify pass after each transfer (D-50)
  resume_backup: true                        # adds --partial
  dry_run: false                             # every run is a dry run
  host_config_backup: true
  unfinished_ttl_hours: 30                   # int >= 1; hours after the END of the last attempt (D-14)
  max_parallel_hosts: 2                      # int >= 1
  job_timeout_minutes: 0                     # int >= 0; 0 = no overall limit (D-38)
  io_timeout_seconds: 600                    # int >= 30; rsync --timeout: stop a stalled transfer (D-38)
  min_free_gb: 50                            # int >= 0
  wake:
    enabled: true
    wait_seconds: 180                        # int >= 0

notifications:                               # optional; both channels default disabled
  email:
    enabled: false
    smtp_host: smtp.example.com
    smtp_port: 587
    starttls: true
    username: you@example.com
    password_file: ~/.config/bn-backup/smtp_password   # must exist, mode 0600 when enabled
    from: you@example.com
    to: [you@example.com]                    # >= 1 when enabled
  signal:
    enabled: false
    signal_cli: /opt/homebrew/bin/signal-cli
    account: "+61400000000"                  # E.164
    note_to_self: true
    recipients: []                           # E.164 numbers; note_to_self or >= 1 recipient required when enabled

hosts:                                       # required, >= 1
  galactica:                                 # host key: [a-z0-9][a-z0-9-]{0,62}
    address: galactica.home.lan              # required: FQDN or .local name (contains a dot), or IP literal
    admin_user: ariel                        # required
    ssh_port: 22                             # default 22

modules:                                     # required, >= 1
  ariel-photo-archive:                       # module name: [A-Za-z0-9_-]{1,64}
    host: galactica                          # must be a key of hosts
    user: ariel                              # required
    src_path: /Volumes/PhotoArchive/Photos   # absolute, no trailing "/", not "/"; external drives allowed (D-40)
    excludes: []                             # rsync --exclude patterns, default []
  ariel-lightroom:
    host: galactica
    user: ariel
    src_path: /Users/ariel/Pictures/Lightroom
    excludes: ["*.lrdata"]                   # Lightroom previews: large, rebuilt by Lightroom
```

**Validation** (`bn-backup config validate` prints *all* errors, then exits 1 if any):
- every rule in the comments above;
- module names unique (YAML dict) **and** not equal to any generated host-config
  module name `<user>-<host>` for any `user@host` in use (only when
  `host_config_backup` is true);
- module names must not be `config.yml`, `backup_report.log`, or start with `.`;
- generated host-config module names `<user>-<host>` must be unique across all
  `user@host` pairs in use (user `a-b` on host `c` and user `a` on host `b-c`
  would both give `a-b-c`), only when `host_config_backup` is true;
- a bare host `address` without a dot that is not an IP is an error; `.local`
  (mDNS) names such as `galactica.local` are valid (D-18);
- `~` in paths expands against the home of the account running the server.

**Not in the config:** OS, CPU, MAC addresses and agent version. These are
discovered and stored in `.state/hosts/<host>.json`.

**`bn-backup config migrate OLD.yml [-o NEW.yml]`:** detects the format version
(no `version` key = v1; `version: 2` = already current → exit 1 with "already
at version 2"). Converting v1 → v2 reads v1 (`settings`
with `backup_directory`, `verify_backup`, `resume_backup`, `dry_run`; `modules`
with `src_path/user/host/os`). It writes v2:
- copies `backup_directory`, `verify_backup`, `resume_backup` (default `true` if absent), `dry_run`;
- groups modules by `host`; each host gets `address: <host>.CHANGE-ME.lan` and
  `admin_user: <user of its first module>`;
- `server.ssh_host: CHANGE-ME`; `server.receive_user: <the user running the command>`;
- adds a YAML comment `# TODO verify` on every guessed line, then prints the
  list of guesses. The output does not pass validation until the `CHANGE-ME`
  placeholders are edited. That is intended.

**`bn-backup config show [--json]`:** prints the validated config with every
default filled in (YAML, or JSON with `--json`). Read-only. Exit 1 with the
validation errors if the config is invalid.

---

## 5. Agent specification

### 5.1 Paths

| Item | macOS | Linux |
|---|---|---|
| Executable | `/Applications/BNBackupAgent.app/Contents/MacOS/bn-backup-agent` | `/usr/bin/bn-backup-agent` |
| CLI symlink | `/usr/local/bin/bn-backup-agent` → executable | – |
| rsync used | `/Applications/BNBackupAgent.app/Contents/Resources/rsync` | `/usr/bin/rsync` |
| Agent home `$AH` | `/Library/Application Support/BNBackupAgent` | `/var/lib/bn-backup-agent` |
| Per-user job | `/Library/LaunchDaemons/ar.bleiben.bn-backup-agent.<user>.plist` (label `ar.bleiben.bn-backup-agent.<user>`) | `/lib/systemd/system/bn-backup-agent@.service`, instance `bn-backup-agent@<user>.service` |
| Sudoers drop-in | `/etc/sudoers.d/bn-backup-agent` | `/etc/sudoers.d/bn-backup-agent` |
| Bundle id / pkg id | `ar.bleiben.bn-backup-agent` | – |

Inside `$AH` (owner, mode):
- `agent.toml` (root, 0644): `server_host`, `server_port`, `server_user`, `admin_user`, `host_name` (the config host key).
- `server_known_hosts` (root, 0644): one known_hosts line for the server.
- `users/` (root, 0755)
  - `users/<user>/` (root, 0755)
    - `job.json` (root, 0644)
    - `state/` (`<user>`, 0700): `id_ed25519` (0600), `id_ed25519.pub` (0644),
      `result.json`, `rsync-<module>.log`, `agent.log`.

The agent resolves `$AH` and the rsync path at compile time per OS. Unit tests
override `$AH` through the env var `BN_BACKUP_AGENT_HOME`. Honour it **only** in
debug builds (`cfg(debug_assertions)`).

### 5.2 `ctl` commands

`ctl` must run as root. If euid ≠ 0, exit 1 with error `not_root`. Every
command writes **one JSON object on stdout**. On failure it writes
`{"error":"<code>","message":"<text>"}` and exits 1. Never print anything else
to stdout.

| Command | Behaviour | Success output |
|---|---|---|
| `ctl setup --host-name H --server-host S --server-port P --server-user U --server-known-hosts-line L --admin-user A --control-key K` | Run by the operator with their password, never through the control key. Create `$AH` tree. Write `agent.toml` and `server_known_hosts`. Write the sudoers drop-in (§5.6), validate it with `visudo -cf`, then install it 0440 root. Install the locked control-key line (§5.11). Enable Wake-on-LAN (§5.8). Idempotent. | `{"ok":true,"wol":"enabled"\|"not_supported"\|"partial","wol_detail":"…"}` |
| `ctl ping` | No side effects. | `{"ok":true}` |
| `ctl info` | No side effects. `users` = users that have been added; `running` = users whose job is running now. | `{"agent_version","protocol_min","protocol_max","os":"darwin"\|"linux","arch":"arm64"\|"x86_64"\|"aarch64","hostname","mac_addresses":[{"iface","mac","wired":bool}],"rsync_path","rsync_version","configured":bool,"users":[…],"running":[…]}` |
| `ctl user-add <user>` | User must exist (`getpwnam`); otherwise error `no_such_user`. Create `users/<user>/` and `state/`. If no key exists, run `ssh-keygen -t ed25519 -N "" -C "bn-backup-agent <user>@<host_name>" -f state/id_ed25519` and chown both files to the user. macOS: install the per-user LaunchDaemon (§5.7). Linux: nothing more to install, because the template unit serves every user. Idempotent. | `{"ok":true,"public_key":"ssh-ed25519 AAAA… comment"}` |
| `ctl user-remove <user>` | Stop the job if running, unload and remove it, delete `users/<user>/`. | `{"ok":true}` |
| `ctl submit <user>` | Read the job JSON from stdin (max 1 MiB). Validate it (§5.4): protocol supported, `user` field equals `<user>`, module names valid, `src_path` absolute, `server` equal to `server_host`/`server_port`/`server_user` and `host_name` equal to `host_name` in `agent.toml` (otherwise error `server_mismatch`). Error `busy` if the job is running. Write `job.json` atomically (temp + rename) and delete `state/result.json`. | `{"ok":true,"job_id":"…"}` |
| `ctl start <user>` | Error `busy` if running. macOS: `launchctl kickstart system/ar.bleiben.bn-backup-agent.<user>`. Linux: `systemctl start --no-block bn-backup-agent@<user>.service`. | `{"ok":true}` |
| `ctl stop <user>` | macOS: `launchctl kill SIGTERM system/<label>`. Linux: `systemctl stop bn-backup-agent@<user>.service`. | `{"ok":true}` |
| `ctl result <user>` | Print `state/result.json` verbatim, or `{"state":"absent"}`. | the result object |
| `ctl log <user> <module>` | Last 2000 lines of `state/rsync-<module>.log`, as `{"lines":[…]}`. | |
| `ctl open-fda-settings` | macOS only (Linux: error `not_supported`). Find the console user (`stat -f %Su /dev/console`). If it is `root` or `loginwindow`, return `{"opened":false}`. Otherwise run `launchctl asuser <uid> sudo -u <console user> open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`. | `{"opened":bool,"console_user":"…"}` |
| `ctl ssh-dispatch <string>` | The forced command of the control key (§5.11). Never called by a person. | the output of the dispatched command |
| `ctl uninstall` | Run by the operator with their password, never through the control key. Remove every per-user job, `$AH`, the sudoers drop-in, the control-key line from the admin account's `authorized_keys`, and on macOS the app, the symlink and `pkgutil --forget ar.bleiben.bn-backup-agent`. | macOS: `{"ok":true}`. Linux: `{"ok":true,"note":"run: sudo apt-get remove bn-backup-agent"}` |

"Running" means: macOS, `launchctl print system/<label>` reports `state = running`;
Linux, `systemctl is-active` returns `active` or `activating`.

### 5.3 `run --user <user>`

Started only by launchd/systemd, as `<user>`. If the effective user ≠ `<user>`,
exit 2. Steps:

1. Read `job.json`. Write `result.json` with `"state":"running"` and the
   `job_id`. All result writes are atomic (temp + rename) into `state/`.
2. Keep awake: macOS spawns `/usr/bin/caffeinate -i -s -w <own pid>`. Linux spawns
   `systemd-inhibit --what=sleep:idle --who=bn-backup-agent --why="backup running" --mode=block sleep infinity`
   and kills it on exit. If `systemd-inhibit` is missing, continue and add a note.
3. If `timeout_seconds` > 0, enforce it across the whole job: on expiry, kill
   rsync (SIGTERM, then SIGKILL after 10 s), mark the current and remaining
   modules `failed` / `timeout`. With 0 there is no overall limit; stalls are
   handled by rsync's own `--timeout` (§5.9).
4. `kind:"probe"` → §5.5. `kind:"backup"` → for each module in order: §5.4 /
   §5.9. A failed module never stops the next, with one exception (D-46): if a
   module ends `drive_missing`, stop the job at once, mark every remaining
   module `failed` / `skipped` and go to step 5. After any rsync failure of a
   `path` module under an external-drive root (§5.5), run the module probe
   again; if it now reports `drive_missing`, that is the module's `error_kind`.
   After a `path` module's transfer ends `ok`, run the verify pass when
   `options.verify` is set (§5.9).
5. Write the final `result.json` with `"state":"done"`. Exit 0, even when
   modules failed; failures are data, not process errors.

Before running rsync for a `path` module, check `src_path` with the same probe
as §5.5. If it fails, mark the module failed with that `error_kind` and skip
rsync.

### 5.4 Job and result schemas (protocol 1)

Job (`job.json`):
```json
{
  "protocol": 1,
  "kind": "backup",                       // "backup" | "probe"
  "job_id": "3f0c…",                      // uuid4 string from the server
  "run_id": "20261110-213000",            // "" for probes
  "user": "sofia",
  "host_name": "athena",
  "server": {"host": "server.home.lan", "port": 22, "user": "ariel"},
  "options": {"verify": false, "partial": true, "dry_run": false, "io_timeout_seconds": 600},
  "timeout_seconds": 0,                   // 0 = no overall limit
  "modules": [
    {"name": "sofia-documents", "type": "path", "src_path": "/Users/sofia/Documents", "excludes": [".DS_Store"], "expect_nonempty": true},
    {"name": "sofia-athena", "type": "host-config"}
  ]
}
```

Result (`result.json`):
```json
{
  "protocol": 1,
  "job_id": "3f0c…",
  "run_id": "20261110-213000",
  "kind": "backup",
  "user": "sofia",
  "agent_version": "2.0.0",
  "state": "done",                        // "running" | "done"
  "started_at": "2026-11-10T10:30:00Z",
  "finished_at": "2026-11-10T10:41:12Z",
  "fda": "granted",                       // "granted" | "denied" | "not_applicable"
  "server_reachable": true,               // probe only; null for backup
  "server_error": null,
  "server_error_kind": null,              // probe only: "server_denied" | "network"
  "notes": [],
  "modules": [
    {"name": "sofia-documents", "status": "ok",          // "ok" | "failed"
     "rsync_exit": 0, "error_kind": null,                 // see §5.10: missing|drive_missing|source_empty|permission|tcc|server_denied|network|stalled|timeout|skipped|other
     "message": "", "files_transferred": 12, "bytes_transferred": 3456789,
     "suspect_count": 0, "suspect_files": []}        // verify pass, §5.9
  ]
}
```
Unknown fields are rejected in jobs and ignored in results (forward compatibility).

`expect_nonempty` (`path` modules only, default `false`, D-55): the server sets
it in every job, probe or backup, when the module's backup already holds data,
that is when `current/<module>/<basename(src_path)>/` exists and has at least
one entry.

### 5.5 Probe job

- **FDA** (macOS): `open()` `/Library/Application Support/com.apple.TCC/TCC.db`
  for reading. Success → `granted`. `EPERM`/`EACCES` → `denied`. Linux → `not_applicable`.
- **Each module:** `path` → these checks in order; the first failure wins:
  1. **Drive mounted (D-40, D-55).** Only when `src_path` is under an
     external-drive root: macOS `/Volumes/`; Linux `/media/`, `/run/media/` or
     `/mnt/`. macOS: the drive is `/Volumes/<name>` (the first component below
     `/Volumes`); it must exist and be a mount point (`statfs` on it reports
     that same path as `f_mntonname`). Linux: `src_path` itself or one of its
     ancestors strictly below the root must be a mount point listed in
     `/proc/self/mountinfo`. Otherwise → `drive_missing`, **even if `src_path`
     exists**: an empty folder left where a drive is normally mounted must never
     be backed up as the archive.
  2. `opendir(src_path)` and read its entries. `ENOENT`/`ENOTDIR` → `missing`;
     `EPERM` on macOS → `tcc`; `EACCES` (or `EPERM` on Linux) → `permission`.
  3. **Empty source (D-55).** If the module has `expect_nonempty: true` and the
     directory has no entries other than `.DS_Store` and `.localized` →
     `source_empty`.
  4. Otherwise → `ok`.

  `host-config` → readable `$HOME` → `ok`.
- **Server reachability, with a real write:** create a temp dir holding one
  small file `probe` (content: the current UTC time) and push it with the
  common rsync prefix of §5.9 plus `--recursive`:
  `<tmpdir>/ <server_user>@<server>:.probe/` (not a dry run, so a server that
  refuses writes is detected). Exit 0 → `server_reachable: true`. Otherwise
  `false`, with the last stderr line in `server_error` and
  `server_error_kind` = `server_denied` or `network`, classified as in §5.10.
- Probe modules carry `rsync_exit: null`.

### 5.6 Sudoers drop-in (D-09)

Exactly one line, admin user from `--admin-user`:
```
<admin_user> ALL=(root) NOPASSWD: <absolute executable path> ctl *
```
macOS executable path: `/Applications/BNBackupAgent.app/Contents/MacOS/bn-backup-agent`
(the server always calls this absolute path, not the symlink). Linux:
`/usr/bin/bn-backup-agent`. Nothing else is passwordless. Package installs and
upgrades always prompt for the admin password.

### 5.7 Per-user job definitions

macOS plist (`/Library/LaunchDaemons/ar.bleiben.bn-backup-agent.<user>.plist`, root:wheel 0644):
`Label`; `ProgramArguments` = [executable, `run`, `--user`, `<user>`];
`UserName` = `<user>`; `RunAtLoad` false; no `KeepAlive`, no `StartInterval`;
`ProcessType` `Standard`; `StandardOutPath` and `StandardErrorPath` =
`$AH/users/<user>/state/agent.log`. Load it with
`launchctl bootstrap system <plist>`. If already loaded, `bootout` first.

Linux unit (`/lib/systemd/system/bn-backup-agent@.service`, shipped in the .deb):
```
[Unit]
Description=BN Backup Agent job for %i
[Service]
Type=oneshot
User=%i
ExecStart=/usr/bin/bn-backup-agent run --user %i
Nice=10
IOSchedulingClass=best-effort
TimeoutStartSec=infinity
```
No `[Install]` section. On Linux `user-add` installs no job file (the template
unit serves every user); it still creates the directories and the push key.

### 5.8 Wake-on-LAN setup (in `ctl setup`, D-24)

- macOS: `pmset -a womp 1`.
- Linux, NetworkManager active (`systemctl is-active NetworkManager`): for each
  connection of type `802-3-ethernet`, run
  `nmcli connection modify <uuid> 802-3-ethernet.wake-on-lan magic`.
- Linux without NetworkManager: write
  `/etc/systemd/network/50-bn-backup-wol.link` with `[Match] Type=ether` and
  `[Link] WakeOnLan=magic`.
- Report `enabled`, `partial` (some interfaces failed) or `not_supported` (no
  wired interface). Never fail `setup` because of WoL.

### 5.9 rsync invocations

Common prefix (argv, no shell):
```
<rsync> --archive --hard-links --numeric-ids --xattrs --delete
        -M--fake-super
        --log-file=<state>/rsync-<module>.log
        --out-format=%i %n
        -e "ssh -i <state>/id_ed25519 -o UserKnownHostsFile=$AH/server_known_hosts
            -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=15
            -o ServerAliveInterval=30 -p <port>"
        --timeout=<options.io_timeout_seconds>
        [--partial if options.partial] [--dry-run if options.dry_run]
```
**No `--compress`, and never `--checksum` in a transfer** (D-50). The `-e` value
is one argv element with the options space-joined as shown. `<server_user>`,
`<server_host>` and `<port>` always come from `agent.toml`, never from the job.

- `path` module: `… [--exclude=<p> for each exclude] <src_path> <server_user>@<server_host>:<module>/`.
  `src_path` has **no trailing slash** (v1 layout: content lands in
  `<module>/<basename(src_path)>/`).
- `host-config` module (two transfers; the module is `ok` only if both are acceptable):
  1. `/etc/hosts` and `/etc/motd` (whichever exist; a missing one is skipped
     and noted) → `<module>/`, **without** `--delete`.
  2. The user's dotfiles: source `$HOME/` (with a trailing slash) →
     `<module>/<user>/` with `--delete` and these filter rules, in this order:
     `--exclude=.Trash --exclude=.cache --include=/.* --exclude=/*`. Only
     top-level entries whose name starts with `.` (and everything inside them)
     are copied, and a dotfile deleted from `$HOME` is deleted from the backup.

Count transferred files from `--out-format` lines whose itemize string starts
with `>f` or `<f`. Sum bytes from `--log-file` lines if available. Otherwise
report 0. Exact stats are informational only.

**Verify pass (D-50).** Only when `options.verify` is true, the job is not a
dry run and the module's transfer ended `ok`, and only for `path` modules: run
the same command again with `--checksum --dry-run` added (and a separate log
file `rsync-<module>-verify.log`). It transfers nothing. Every `--out-format`
line whose itemize string starts with `<f` (a push marks sent files with `<`;
accept `>f` too) and has `c` as its 3rd character
while the 4th (`s`) and 5th (`t`) are `.` (0-based indexes 2, 3 and 4) names a
file whose content differs
although size and time match. Report them in the module result as
`suspect_count` and `suspect_files` (the first 500 paths, relative to the
module). The module stays `ok` whatever the pass finds; if the verify pass
itself fails, add a note `verify failed: <reason>` and keep the module `ok`.
Nothing is ever overwritten because of this pass.

### 5.10 Outcome classification (agent side, D-17)

First match wins:

| Condition | status | error_kind |
|---|---|---|
| exit 0 or 24 | ok | null |
| src pre-check failed | failed | missing / drive_missing / source_empty / permission / tcc |
| not run because an earlier module was `drive_missing` | failed | skipped |
| killed by job timeout | failed | timeout |
| drive vanished during the transfer (re-probe after failure, §5.3) | failed | drive_missing |
| exit 30 (no progress for `io_timeout_seconds`) | failed | stalled |
| a stderr line tagged `[receiver]` or `[generator]` contains `Operation not permitted` or `Permission denied` | failed | server_denied |
| exit 255, 5, 10, 12, 35, or stderr contains `ssh:` / `Connection refused` / `Could not resolve` | failed | network |
| exit 23 and stderr contains `Operation not permitted` (macOS) | failed | tcc |
| exit 23 and stderr contains `Permission denied` | failed | permission |
| anything else | failed | other |

`server_denied` means the *server* refused the write (on a Mac server: "Allow
full disk access for remote users" is off, or the drive is read-only). rsync 3
tags each error line with the role that produced it (rsync 3.4 capitalises the
server-side roles, `[Receiver]`, so match without case; an `rrsync error:` line
reporting a denial also counts); when no line carries a
role tag, the `tcc` / `permission` rows apply and the server's hint (§6.13)
names both possible causes.

`message` = the last 8 non-empty stderr lines, joined with `\n`.

### 5.11 The locked control key (D-48)

`ctl setup --control-key K` makes sure the admin account's
`~/.ssh/authorized_keys` (created 0600 in `~/.ssh` 0700 if missing, owned by
the admin user) contains exactly one line ending in the comment
`bn-backup-server`:

```
restrict,command="/usr/bin/sudo -n <agent executable> ctl ssh-dispatch \"$SSH_ORIGINAL_COMMAND\"" <key type> <key data> bn-backup-server
```

Any earlier line with that comment is replaced. Other lines are untouched.

`ctl ssh-dispatch <string>`:
- `<string>` is what the server asked to run. Empty (an interactive login
  attempt) → `{"error":"no_command"}`, exit 1.
- Split it with the `shell-words` crate. The first word must be `ctl` and the
  second one of `ping`, `info`, `user-add`, `user-remove`, `submit`, `start`,
  `stop`, `result`, `log`, `open-fda-settings`. Anything else, including
  `setup`, `uninstall` and `ssh-dispatch`, → `{"error":"not_allowed"}`, exit 1.
- Then behave exactly as if that `ctl` command had been invoked directly, with
  stdin passed through (needed by `submit`).

The sudoers rule of §5.6 already covers `ctl ssh-dispatch`.

---

## 6. Server specification

### 6.1 The operator account, install and `server init` (D-21, D-31)

There is **no dedicated backup account**. The server runs as **the operator**:
the admin account on the server that installs and runs `bn-backup`.
`server.receive_user` in the config names that account, and agents push to it.
No wrapper script and no sudoers rule exist on the server.

- **Install:** the operator runs `uv tool install <wheel URL or path>` in their
  own account (upgrade: the same with `--force`). The executable is
  `~/.local/bin/bn-backup`.
- **Who may run it:** every command refuses to run as root ("run bn-backup as
  your own account, without sudo"). The one exception is `schedule install` and
  `schedule remove`, which must run as root through `sudo` (§6.15). Every
  command except `server init`, `config …` and `--version` also refuses to run
  when the current user is not `server.receive_user`.
- **Per-operator paths** (`~` is the operator's home):

  | What | Path |
  |---|---|
  | Config | `~/.config/bn-backup/config.yml` (0600, directory 0700) |
  | Control key | `~/.ssh/bn-backup_ed25519` and `.pub`, comment `bn-backup-server` |
  | rrsync | `~/.local/libexec/bn-backup/rrsync` |
  | Release cache | `~/.cache/bn-backup/releases/<version>/` |
  | Abort marker | `~/.local/state/bn-backup/abort-pending.json` |
  | Run lock | `~/.local/state/bn-backup/lock` (§6.8) |
  | Log | macOS `~/Library/Logs/bn-backup.log`; Linux `~/.local/state/bn-backup/bn-backup.log` |

`bn-backup server init` (no sudo, idempotent):
1. Refuse to run as root.
2. Create `~/.ssh` (0700) if missing. Create the control key if missing:
   `ssh-keygen -t ed25519 -N "" -C "bn-backup-server" -f ~/.ssh/bn-backup_ed25519`.
   Never touch the operator's other keys.
3. Install vendored rrsync (§6.2).
4. If no config exists: write a commented template with
   `receive_user: <current user>` (mode 0600), print "edit it, then run
   `bn-backup server init` again", exit 0.
5. With a valid config: create the layout under `backup_directory` (§6.9),
   owned by the operator, mode 0700 on the top directory. If the parent is not
   writable by the operator, fail and say so.
6. **Adopt a v1 backup:** if `<backup_directory>/previous/` exists and
   `removed/` does not, rename `previous/` → `removed/`. Existing
   `current/<module>/` folders are used as they are; in v1 they already belong
   to the operator. Print what was adopted.
7. Check that the SSH server answers on `localhost:<ssh_port>`; if not, print
   how to turn on Remote Login (macOS) or install `openssh-server` (Linux). On
   macOS also print the reminder to turn on "Allow full disk access for remote
   users"; it cannot be detected here, the probe detects it later (§5.5).
8. Run the server checks of §6.5 and print them.

Linux is identical apart from the macOS-only hints.

### 6.2 rrsync (vendored)

Ship upstream `support/rrsync` from rsync 3.4.1 as `bn_backup/vendor/rrsync`,
with its license. At `server init`, copy it to `~/.local/libexec/bn-backup/rrsync`
(0755) and rewrite its `RSYNC = '/usr/bin/rsync'` constant to the absolute
path of an rsync that reports version ≥ 3.2.3:
- macOS: Homebrew's (`$(brew --prefix rsync)/bin/rsync`), because
  `/usr/bin/rsync` there is openrsync. Missing or too old → fail with
  "brew install rsync".
- Linux: `/usr/bin/rsync`. Missing or too old → fail with
  "sudo apt install rsync".

Set its shebang to the server's own Python interpreter.

### 6.3 Managed `authorized_keys` on the server

The operator's `~/.ssh/authorized_keys` on the server contains a block the server owns:
```
# BEGIN bn-backup managed — do not edit
restrict,command="<rrsync path> -wo <backup_directory>/.staging/<host>/<user>" <public key>
…
# END bn-backup managed
```
It is regenerated from `.state/keys/<host>/<user>.pub` (sorted by host, user)
whenever keys change. Lines outside the block are preserved. Write atomically,
0600.

### 6.4 SSH transport (server → hosts, D-48)

OpenSSH through `subprocess`, as the operator. There are two kinds of
connection, and they must never be mixed.

**Control connection** (non-interactive; everything in normal operation):
```
ssh -i ~/.ssh/bn-backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes
    -o ConnectTimeout=10 -o ServerAliveInterval=15 -o StrictHostKeyChecking=yes
    -o ControlMaster=auto -o ControlPath=~/.ssh/cm-bn-%C -o ControlPersist=60
    -p <port> <admin_user>@<address> <ctl command>
```
`<ctl command>` is `shlex.join(["ctl", <subcommand>, *args])`, for example
`ctl info`. On the host the control key is locked (§5.11): sshd ignores the
requested program and hands this string to `ctl ssh-dispatch`. Parse stdout as
JSON. Timeout 60 s per call, 120 s for `user-add`. The control key can do
nothing else: no shell, no `scp`, no port forwarding.

**Operator connection** (interactive; only inside `hosts bootstrap`,
`agent upgrade` and `hosts remove`): plain `ssh -t -p <port>
<admin_user>@<address> <command>` and `scp -P <port> …`, using the operator's
own SSH configuration and credentials (their keys, their agent or a typed
password). Never pass the control key here. `StrictHostKeyChecking=accept-new`
only on the first contact during bootstrap. Passwords are typed by the operator
at the terminal; the program never reads or stores them.

**Reachability** is a TCP connect to `(address, ssh_port)` within 10 s. It
needs no login.

### 6.5 `bn-backup status [--json]` (the board)

Three views of the same checks (D-33):
- `bn-backup status [--json] [--no-wake]`: server checks + every `user@host` row.
- `bn-backup server status [--json]`: server checks only. Exit 0 green, 2 red.
- `bn-backup agent status [HOST] [--json] [--no-wake]`: host rows only, for all
  hosts or one. Exit 0 green, 2 red.
All three share one implementation in `status.py`.

**Read-only (D-49).** Status takes no lock and never writes `run.json`, the
config, the state directory or anything on a host's set-up. It only sends
Wake-on-LAN packets and runs probe jobs (whose single side effect is the tiny
`.probe/` folder in each user's staging directory). If a run holds the lock
(§6.8), print the run progress from `run.json` and do **not** probe hosts.

Server checks (all must pass for the server row to be green):

| Check | Rule |
|---|---|
| config | valid |
| volume | `backup_directory` exists, and its mount point (from `os.stat` device change / `diskutil info -plist <mountpoint>`) is mounted |
| apfs_case_sensitive | `diskutil info -plist` → `FilesystemType` = `apfs` and `FilesystemUserVisibleName` contains `Case-sensitive` (Linux: skip) |
| ownership | `diskutil info -plist` → `GlobalPermissionsEnabled` true (Linux: skip) |
| volume_writable (D-54) | in `.state/`: create a small file, clone it (§6.11), delete both. Catches a read-only drive, macOS privacy protection blocking the server process, and a Linux filesystem without clone support |
| free_space | free ≥ `min_free_gb` GiB |
| rrsync | file exists, executable, and its `RSYNC` path runs `--version` ≥ 3.2.3 |
| promotion | no `.state/promotion.json` (red: "a promotion was interrupted; `bn-backup run` finishes it") |
| lock | no live run (lock file on the internal disk, §6.8) |

`volume_writable` is the one check that writes. It runs in `run` and in
`server init`. The status views replace it with `os.access(<.state>, os.W_OK)`,
so they stay read-only.

If an abort marker exists (§6.17), all three views print the note "clean-up
pending from aborted run <id>; the next `bn-backup run` deletes staging first".
It is a note, not a red check. `status` never performs the clean-up.

Per `user@host` row, checks in this order. Stop at the first red; later cells
show `–`:

1. `dns`: `socket.getaddrinfo(address)`.
2. `reachable`: TCP connect (§6.4). If it fails and `wake.enabled` and not
   `--no-wake`, Wake-on-LAN (§6.10), then recheck.
3. `agent`: `ctl info` over the control connection works and the protocol is
   supported. Red reasons: the login is refused or the agent is missing →
   "run bn-backup hosts bootstrap <host>"; `protocol` → "run bn-backup agent
   upgrade <host>".
4. `user`: `ctl info` lists the user under `users`. If not → red "run
   bn-backup hosts configure <host>". Status never configures anything.
5. `idle`: the user is not listed under `running`. In `status`: red "a job
   from an earlier run is still running". In the gate of `run` (§6.7 step 5):
   first send `ctl stop <user>` and poll `ctl info` for up to 30 s; red only if
   it is still running after that.
6. `probe`: submit + start a probe job (§5.5) and poll every 2 s, up to 120 s.
   Red on `fda: denied` ("Switch on BNBackupAgent in Full Disk Access on <host>"),
   on any module not `ok` (show module + error_kind), or on
   `server_reachable: false` (with the hint for `server_error_kind`, §6.13).

Probes for different hosts run in parallel (`max_parallel_hosts`). Users on
the same host run one after another. Extra columns: `last complete`
(from `.state/last_complete.json`) and `pending` (UNFINISHED run: red module
count and hours left; an UNFINISHED run past its TTL is displayed as `EXPIRED`).
Exit code: 0 all green, 2 anything red, 1 error.

### 6.6 `hosts …` and `agent upgrade`

**`hosts list`**: one row per host in the config plus any host known only in
`.state/hosts/` (marked "not in config"): host, address, os/arch, agent version,
bootstrapped yes/no, users.

**`hosts add HOST [--address A] [--admin-user U] [--ssh-port P] [--no-bootstrap]`** (D-34):
1. Refuse if `HOST` already exists in `hosts:` or is not a valid host key.
2. Prompt for every value not given as an option: address (must pass the
   address rule of §4), admin account, SSH port (default 22).
3. Insert the block at the end of `hosts:` with ruamel.yaml in round-trip mode, so
   existing comments, order and formatting are kept. Write it atomically (see §4).
4. Re-validate the whole file. If it is invalid, restore the original bytes and
   exit 1 with the errors.
5. Unless `--no-bootstrap`, run `hosts bootstrap HOST`. Remind the operator
   that modules for this host are added by editing the config.
Editing the config by hand and running `hosts bootstrap HOST` is equally
supported.

**bootstrap** (sequential, interactive), per host not yet bootstrapped (or the
named one). Steps 2–5 use the **operator connection** (§6.4):
1. DNS + TCP reachability on `ssh_port`. Red → stop for this host.
2. `ssh -t … "uname -s; uname -m"` → os/arch. Store them in
   `.state/hosts/<host>.json`, together with `address`, `ssh_port` and
   `admin_user` from the config. Bootstrap, `configure` and `agent upgrade`
   refresh these three fields; `hosts remove` needs them after the host has
   left the config.
3. For every `user` in this host's modules: `ssh … id -u <user>`. A missing user → red, stop.
4. Get the package for the server's version (§6.12), `scp` it, then install:
   - Linux: copy to `/tmp/`, run `ssh -t … sudo apt-get install -y /tmp/bn-backup-agent_<v>_<arch>.deb`, then delete it.
   - macOS: copy to `/Users/Shared/bn-backup-agent-<v>.pkg`, run `ssh -t … sudo installer -pkg <that> -target /`. Leave the file.
5. `ssh -t … sudo <agent> ctl setup …` with `--server-user <receive_user>`,
   `--control-key "<contents of ~/.ssh/bn-backup_ed25519.pub>"` and the
   server's known_hosts line. Build that line from
   `/etc/ssh/ssh_host_ed25519_key.pub` on the server: `<ssh_host> <key>`, or
   `[<ssh_host>]:<port> <key>` if port ≠ 22.
6. Verify the **control connection**: `ctl ping`. Failure → red, stop. Every
   later step uses the control connection.
7. `hosts configure <host>` (below).
8. macOS: `ctl open-fda-settings`, print
   "Go to <host> and switch on BNBackupAgent in System Settings → Privacy & Security → Full Disk Access",
   then run a probe every 15 s for up to 30 min until `fda: granted`. Ctrl-C
   leaves the host bootstrapped but red; re-running bootstrap resumes at this step.
9. `ctl info`. Store mac_addresses, agent_version and rsync_version.
10. Run the status row (§6.5) and print it.

Each step is skipped when `.state/hosts/<host>.json` shows it is done and a
cheap check confirms it (`ctl ping` / `ctl info` for install and setup).
`bootstrapped: true` is set after step 9.

**configure** (non-interactive, control connection). It runs only when the
operator calls it, or as step 7 of bootstrap; `status` and `run` never call it
(D-49). For each user in the host's modules that `ctl info` does not list:
`ctl user-add <user>`. Store the returned public key in
`.state/keys/<host>/<user>.pub`, regenerate authorized_keys (§6.3) and create
`.staging/<host>/<user>/` (owned by the operator, 0700). Users no longer
referenced are left as they are (D-27).

**forget HOST**: remove its keys from `.state/keys/` and authorized_keys,
and delete `.state/hosts/<host>.json`. Touches nothing on the host. Works for
hosts not in the config.

**remove HOST** (D-35): full clean-up of a host no longer wanted.
1. Refuse (exit 1) while `HOST` is still under `hosts:` in the config:
   "remove it from the config first". Refuse while a run holds the lock.
2. Use the address/port/admin user stored in `.state/hosts/<host>.json`. If
   there is no record, refuse with "unknown host; nothing to remove".
3. Host must be reachable. Otherwise exit 1 with "host unreachable; use
   `hosts forget HOST` to clean up only the server side".
4. Over the operator connection: `ssh -t … sudo <agent> ctl uninstall` (this
   also removes the control-key line). Linux: then `ssh -t … sudo apt-get
   remove -y bn-backup-agent`.
5. `hosts forget HOST`.
Backup data in `current/`, `removed/` and `snapshots/` is never touched by
`remove` or `forget`.

**agent upgrade [HOST]**: over the operator connection, bootstrap steps 4 and 5
(setup is idempotent); then step 6; then step 8 only if a probe reports
`fda: denied` (expect this on every macOS upgrade, D-07); then step 9.

### 6.7 `bn-backup run [--dry-run] [--fresh] [--no-wake]` (D-13…D-17, D-30, D-45, D-46, D-51, D-52)

Exit codes: 0 COMPLETE (or dry run with everything green), 1 error or NOT
STARTED, 2 UNFINISHED (or dry run with red), 3 lock held, 4 ABORTED.

**A dry run changes nothing (D-51).** With `--dry-run` or `settings.dry_run`,
nothing is written to `backup_directory` (no staging, no `run.json`, no
history, no report file), nothing is deleted, and no notification is sent. The
only traces are the lock file and the log file (both on the internal disk),
the tiny `.probe/` folder that the gate's probes write in each user's staging
directory (§5.5, D-56), and each agent's own result and log files on its host.
`--dry-run` together with `--fresh` is refused (exit 1).

Algorithm (`clock` injectable; all timestamps UTC ISO 8601 in files, local time on screen):

1. **Lock** (§6.8). It is on the internal disk, so this works even when the
   backup drive is missing (step 3 then reports NOT STARTED). Held → exit 3.
   Keep the server awake for the whole command: macOS
   `caffeinate -i -s -w <pid>`; Linux
   `systemd-inhibit --what=sleep:idle --who=bn-backup --why="backup run" --mode=block sleep infinity`,
   killed at the end (if `systemd-inhibit` is missing, continue and log a note).
2. **Recover** (D-52). If `.state/promotion.json` exists, finish it (§6.9):
   after that the interrupted run is `COMPLETE`, with its report written and its
   notification sent (subject as in §6.14 plus " (finished after an
   interruption)"). Then, if an abort marker exists, do the abort clean-up
   (§6.17). Then continue with a new plan. *Dry run:* if a journal or a marker
   exists, do nothing and exit 1 with "an interrupted run needs finishing first:
   run `bn-backup run`".
3. **Server checks** (§6.5 server part, D-32, D-54). Any red → nothing changed;
   unless dry run, send a notification with subject
   `[bn-backup] NOT STARTED — <first failing check>` and the full check list;
   exit 1. (Dry run: skip `volume_writable`.)
4. **Load/plan** from `.state/run.json`. This step only *plans*; what it may
   write is stated per case, and a dry run writes none of it.
   - none, or `COMPLETE`, `EXPIRED` or `ABORTED` → new run.
   - `RUNNING` although the lock was free (the previous process died) → treat as
     `UNFINISHED`: its `pending` modules become red "interrupted", and a missing
     `last_attempt_finished_at` is set to `last_attempt_at`.
   - `--fresh` (D-51, D-57): plan a new run, but change nothing yet. Only
     after the gate of step 5 has passed: if the old run is `UNFINISHED`, set
     it to `EXPIRED` with reason "discarded by --fresh" and write history;
     then delete `.staging/` entirely (§6.9 invariant). If the run is NOT
     STARTED, staging and the old run stay exactly as they were. `--fresh`
     never touches `current/`, `snapshots/` or `removed/`.
   - `UNFINISHED` and `now − last_attempt_finished_at ≥ unfinished_ttl_hours` →
     set status `EXPIRED`, write history, remember `previous_expired = true`,
     then new run. **Keep `.staging/`** (D-39): the new run marks every module
     `pending`, and existing staging dirs are the rsync basis, so data already
     transferred is not sent again. Reconcile staging with the config as in
     "Resume" (delete staging of removed/changed modules).
   - `UNFINISHED` otherwise → resume.
   - New run: `run_id` = local start time `YYYYMMDD-HHMMSS`; every module (config
     modules + generated `<user>-<host>` host-config modules when enabled)
     `pending`; `first_attempt_at = now`; `config_sha256` = hash of the config
     file bytes.
   - Resume: reconcile with the current config. Modules added → `pending`.
     Modules removed → dropped from the run, and their staging dir deleted.
     Modules whose `host`, `user`, `src_path` or `excludes` changed → `pending`,
     and their staging dir deleted. Then every module not `green` becomes
     `pending`. `attempts += 1`, `last_attempt_at = now`. These changes are
     saved only after the gate has passed.
5. **Pre-flight gate (D-45)**: for every host with pending modules, run the
   status row checks (§6.5, including wake, and stopping a leftover job as
   described there) once per `user@host`. If **any** row is red (unreachable,
   agent missing or too old, user not set up, a job that will not stop, FDA
   denied, a module `missing` / `drive_missing` / `source_empty` / `permission` / `tcc`, server
   not reachable or `server_denied`), the run is **NOT STARTED**: print the
   board; unless dry run, send a notification with subject
   `[bn-backup] NOT STARTED — <host>: <reason of the first red row>` and the
   board as body; do not create a run, and leave an in-time `UNFINISHED` run
   byte-for-byte as it was (no `attempts` increment, no timestamp change);
   exit 1. Only when every row is green (and not a dry run): apply a pending
   `--fresh` (step 4), then write `run.json` with status `RUNNING`.
6. **Prepare staging** (not in a dry run) for each pending module: ensure
   `.staging/<host>/<user>/` exists. If `.staging/<host>/<user>/<module>/`
   does not exist, clone `current/<module>/` there (§6.11). If `current/<module>/`
   is missing, create an empty directory. Then delete every top-level entry of
   the staging module that the transfer will not refresh: for a `path` module,
   everything except `<basename(src_path)>` (a folder left from an earlier
   `src_path` would otherwise stay forever, because `--delete` works only
   inside the transferred folder); for a `host-config` module, `hosts` and
   `motd` (they are sent again).
7. **Jobs**: a thread pool of `max_parallel_hosts`, one task per host. Each task
   handles its users one after another. Per user: `ctl submit` (one backup job
   with all that user's pending modules, `timeout_seconds = job_timeout_minutes*60`,
   options `partial` = `resume_backup`, `verify` = `verify_backup`, `dry_run`,
   `io_timeout_seconds`), `ctl start`, then poll `ctl result` every 10 s until
   `state == "done"` and `job_id` matches. Never rely on the result file
   alone: whenever a poll finds no finished result for this `job_id`, also call
   `ctl info`. If the user is not under `running` on two consecutive polls, at
   least 30 s after `ctl start`, the job ended without reporting (the host
   restarted, or the agent crashed): mark its modules `red` "the backup job
   stopped without reporting a result". A result left at `"state":"running"` by
   a dead job must never hold the run forever. Poll failures: retry; after 5
   consecutive minutes of failure, mark that job's modules `red` "lost contact
   with host" (they are retried by the next run; the gate of that run stops the
   leftover job first). Only if `job_timeout_minutes` > 0: if no result within
   `job_timeout_minutes + 5 min`, `ctl stop` and mark them `red` "timeout". With
   0 the server waits as long as the job reports `running` (stalls are caught by
   rsync `--timeout` on the agent, D-38). Map results: `ok` → `green` (keeping
   `suspect_count` / `suspect_files`); `failed` → `red` with `error_kind` +
   message. After each job, fetch `ctl log` for every red module into
   `logs/<run_id>/<host>-<user>-<module>.log`. Save `run.json` after every job
   (atomic write). **Critical events (D-46):** on every poll cycle also check the
   backup volume (the `volume` server check); if a job result contains a module
   with `error_kind: drive_missing`, or the volume check fails twice in a row,
   stop everything and follow §6.17. *Dry run:* same jobs with `dry_run: true`
   and `verify: false`; results are kept in memory only, no logs are fetched,
   and the critical-event rules do not apply (a `drive_missing` result is just
   red).
8. **Decide**:
   - dry run: print one line per module (would run / would fail and why). Exit
     0 if all green, else 2. Nothing was written.
   - all modules green → **promote** (§6.9), which ends with status `COMPLETE`.
   - else → status `UNFINISHED`, `last_attempt_finished_at = now` (the
     `unfinished_ttl_hours` clock starts here, D-14).
9. **Report** (§6.13) and **notify** (§6.14), not in a dry run. Write
   `.state/history/<run_id>.json` (a copy of the final run.json), overwriting on each attempt.
10. Release the lock. Exit 0 / 2.

Ctrl-C / SIGTERM: stop polling, send `ctl stop` to running jobs (best effort,
10 s), mark their unfinished modules red "interrupted", set `UNFINISHED` with
`last_attempt_finished_at = now`, save, release the lock, exit 2. (During a
promotion, finish the current step, leave the journal and exit; the next run
recovers.)

`run.json` schema:
```json
{
  "run_id": "20261110-213000", "status": "UNFINISHED", "mode": "mirror",
  "first_attempt_at": "…", "last_attempt_at": "…", "last_attempt_finished_at": "…",
  "completed_at": null,
  "attempts": 2, "config_sha256": "…", "previous_expired": false, "reason": null,
  "abort": null,   // ABORTED only: {"cause": "backup_volume_lost"|"source_drive_missing", "host", "user", "module", "drive", "at"}
  "modules": {
    "sofia-documents": {"host": "athena", "user": "sofia", "type": "path",
      "src_path": "/Users/sofia/Documents", "excludes": [".DS_Store"],
      "status": "red", "error_kind": "tcc", "reason": "…", "attempt": 2,
      "finished_at": "…", "files_transferred": 0, "bytes_transferred": 0,
      "suspect_count": 0, "suspect_files": []}
  }
}
```
`status` is one of `RUNNING`, `UNFINISHED`, `COMPLETE`, `EXPIRED`, `ABORTED`
(D-15). `RUNNING` is written at the end of step 5 and replaced at step 8 (or by
§6.17). NOT STARTED is an outcome of the command, never a run status.
Per-module `status` is `pending | green | red`.

### 6.8 Lock

`~/.local/state/bn-backup/lock`, on the server's internal disk (D-56), so a
missing backup drive is reported as NOT STARTED instead of failing to lock.
Create the directory (0700) if missing, open the file with `O_CREAT`, take
`fcntl.flock(LOCK_EX | LOCK_NB)` and hold it for the process lifetime; if it is
busy, retry for up to 2 s before giving up. Write
`{"pid","hostname","started_at","command"}` into it for display. If the lock
cannot be taken → lock held (exit 3). If `run.json` says `RUNNING` but the lock
is free, the previous process died: treat it as `UNFINISHED`, with its pending
modules red "interrupted" (D-15).

Commands that only look at the lock (`status`, `server status`, `runs cancel`)
never create it: a missing file means no run; otherwise they test it with
`flock(LOCK_SH | LOCK_NB)` and release it at once.

### 6.9 Layout and promotion (D-20, D-23, D-52)

```
<backup_directory>/
  current/<module>/  current/config.yml  current/backup_report.log
  removed/                               (v1 called it previous/)
  snapshots/<YYYYMMDD-HHMMSS>/<module>/
  .staging/<host>/<user>/<module>/
  .trash/<run_id>/<module>/
  .state/{run.json, promotion.json, last_complete.json, last_report.log,
          hosts/<host>.json, keys/<host>/<user>.pub, history/<run_id>.json}
  logs/<run_id>/
```

Non-module entries in `current/`: `config.yml`, `backup_report.log`, and any
`*.yml`/`*.yaml` file (v1 leftovers).

The **module set** of a run = the config's modules plus the generated
host-config modules (`<user>-<host>`, when `host_config_backup` is on).

**Promotion** (all on the same filesystem; only `os.rename`, `shutil.rmtree`,
`shutil.copy2`, `os.makedirs` for parent folders and small file writes):
1. Build the journal `.state/promotion.json`:
   `{"run_id","mode","snapshot_name","completed_at","report","steps":[{"op","src","dst","done":false},…]}`
   with paths relative to `backup_directory`, `completed_at` = now, and
   `report` = the full report text (§6.13), so that a recovery can finish
   without recomputing anything.
   `snapshot_name` (snapshot mode) names the backup being *replaced*:
   `completed_at` of `.state/last_complete.json` as local time
   `YYYYMMDD-HHMMSS`; if there is no `last_complete.json` (a v1 backup) it is
   `00000000-000000-pre-v2`, which sorts as the oldest. If
   `snapshots/<snapshot_name>` already exists, append `-2`, `-3`, ….
   Steps, in order:
   - for each module in the module set (sorted by name):
     - if `current/<m>` exists: `rename current/<m> → .trash/<run_id>/<m>` (mirror)
       or `→ snapshots/<snapshot_name>/<m>` (snapshot);
     - `rename .staging/<host>/<user>/<m> → current/<m>`;
   - for each directory in `current/` that is **not in the module set** and is
     not a non-module entry: `rmtree removed/<m>` (if exists), then
     `rename current/<m> → removed/<m>`; if at least one moved:
     `copy current/config.yml → removed/config.yml` and
     `copy current/backup_report.log → removed/backup_report.log` (if they exist);
   - `write current/config.yml` (the exact config bytes used by this run);
   - `write current/backup_report.log` (the journal's `report`);
   - `rmtree .trash/`;
   - snapshot mode: `prune snapshots` (keep the newest `snapshot_keep`
     directories by name; delete the rest);
   - `rmtree .staging/`, then recreate `.staging/<host>/<user>/` for every
     configured user (rrsync needs them);
   - `finalize`: set `run.json` to `COMPLETE` with the journal's
     `completed_at`, write `.state/last_complete.json`
     (`{"run_id","completed_at"}`), `.state/last_report.log` and
     `.state/history/<run_id>.json`.
2. Execute the steps in order, saving the journal after each with `done:true`.
   Every step must be idempotent: a rename whose `src` is missing and whose
   `dst` exists counts as done; `finalize` may be repeated.
3. Delete the journal.

**Recovery** is step 2 of `bn-backup run` (§6.7) and nothing else: execute the
journal's remaining steps, delete the journal, then send that run's
notification. Until then `status` shows the `promotion` check red.

`snapshot_keep` counts snapshots only; `current/` is in addition to them.
Switching from snapshot to mirror mode leaves existing snapshots untouched.

**Invariant:** whenever `.staging/` is deleted (promotion, `--fresh`, abort
clean-up §6.17 — never on EXPIRED, D-39, and never in a dry run), immediately
recreate `.staging/<host>/<user>/` (owner: the operator, 0700) for every
`user@host` in the config. rrsync refuses to start if its directory is missing.

### 6.10 Wake-on-LAN (server side)

For a host failing `reachable`: for every MAC in `.state/hosts/<host>.json`,
send the magic packet (6×`0xFF` + 16× the MAC) by UDP to `255.255.255.255`,
ports 9 and 7, with `SO_BROADCAST`. Recheck every 15 s until `wait_seconds`.
Hosts with no known MAC: skip waking and add a note.

### 6.11 Cloning

macOS: `clonefile(src, dst, CLONE_NOFOLLOW)` via `ctypes` on libSystem, called
on the **directory**. It clones the whole tree, including extended attributes.
On failure, raise. Never fall back to hard links (D-20).
Linux: `cp -a --reflink=always src dst`. If that fails,
raise "filesystem without reflink support is not supported".
Tests only: if `BN_BACKUP_TEST_CLONE=copy` is set, use `shutil.copytree(symlinks=True)`.
Read the variable only in `clone.py`.

### 6.12 Release packages (D-29)

`releases.py` downloads from
`https://github.com/bleiben-labs/backup-orchestrator/releases/download/v<version>/<file>`
into `~/.cache/bn-backup/releases/<version>/`. It verifies each file
against the release's `SHA256SUMS` and refuses on mismatch. If the network is
unavailable, it uses a cached, already verified file. `--agent-package PATH`
on `bootstrap`/`agent upgrade` overrides the download (development). Files:
`bn-backup-agent-<v>.pkg`, `bn-backup-agent_<v>_amd64.deb`,
`bn-backup-agent_<v>_arm64.deb`. Pick the .deb by `uname -m`: `x86_64` →
amd64, `aarch64` → arm64.

### 6.13 Report

Human report (written to `current/backup_report.log` on COMPLETE, to
`.state/last_report.log` always, and printed at the end of the run):
```
Backup Report
====================

Run:      20261110-213000   (attempt 2)
Status:   UNFINISHED — re-run before 2026-11-12 03:45 to complete it
Started:  …   Finished: …
Mode:     mirror

Successful:
  - sofia-documents (athena/sofia)
Failed:
  - ariel-lightroom (galactica/ariel): tcc — Operation not permitted …
    hint: Switch on BNBackupAgent in Full Disk Access on galactica.

Files to check (verify_backup):
  - ariel-photo-archive: 2 files differ from their backup although date and size match
      Photos/2019/DSC_0412.NEF
      Photos/2021/IMG_7781.CR3

# Date: 20261110-214512
```
The "Files to check" section appears only when some module has
`suspect_count > 0` (list at most 20 paths per module, then "… and N more; see
`bn-backup runs show <run_id>`"). It is followed by this fixed explanation:
"One of the two copies of each file is damaged. Nothing was overwritten. Open
the original and the backup copy (in current/<module>/ on the server) and keep
the good one: copy the backup over the original, or re-save the original so
the next run copies it."

Port v1's `RSYNC_EXIT_CODES` table and `_rsync_hint` logic (§10) into
`report.py` to produce `hint:` lines. Hints, each written for a non-specialist
reader (photographers) with one concrete next step:

| error_kind | Hint |
|---|---|
| `tcc` | Switch on BNBackupAgent in Full Disk Access on <host>. If it is already on, the server may have refused the write: check "Allow full disk access for remote users" on the server |
| `server_denied` | The server refused to write to the backup drive. On a Mac server: System Settings → General → Sharing → Remote Login → ⓘ → turn on "Allow full disk access for remote users", and check the drive is not read-only |
| `permission` | <user> cannot read some files in <src_path> on <host>; fix their ownership or exclude them |
| `missing` | <src_path> does not exist on <host>; check the path in the config |
| `drive_missing` | Is the external drive <name> connected to <host>? Connect it and run again |
| `source_empty` | <src_path> on <host> is empty, but its backup is not. If a drive belongs there, connect it and run again. If you emptied the folder on purpose, remove the module from the config (its backup moves to removed/) |
| `network` | <host> could not reach the server; check the network and the names |
| `stalled` | No progress for <io_timeout_seconds> s; check the network or a sleeping drive |
| `timeout` | The job ran longer than job_timeout_minutes; raise it or set it to 0 |
| lost contact | The server lost <host> during the run; check that it is awake and on the network, then run again |
| stopped without a result | The backup job on <host> stopped without reporting; check whether <host> restarted, then run again |

The "re-run before" time is `last_attempt_finished_at + unfinished_ttl_hours`.
For `ABORTED` the status line reads "ABORTED — <drive> on <machine> was
unplugged during the run; everything staged was deleted. Reconnect it and run
again; the backup starts from zero. Your last complete backup is untouched.".

### 6.14 Notifications (D-25)

At the end of every non-dry run, after the report. Subject:
`[bn-backup] COMPLETE — <n>/<n> modules`, `[bn-backup] UNFINISHED — <r> of <n> modules red`
or `[bn-backup] ABORTED — <backup drive unplugged | <drive> unplugged on <host>>`.
If any module has suspect files, append ` — <k> files to check` to the subject.
NOT STARTED notifications are sent from steps 3 and 5 of §6.7.
Body: the report text. If `previous_expired`, add the line
"Note: the previous run was not completed within <unfinished_ttl_hours> h of its last attempt; every module was backed up again (data already copied was reused).".
- Email: `smtplib.SMTP(host, port, timeout=30)`, `starttls()` if configured,
  `login(username, password_file contents stripped)`, `send_message`.
- Signal: `[signal_cli, "-a", account, "send", "--note-to-self", "-m", text]`
  if `note_to_self`, and `[signal_cli, "-a", account, "send", "-m", text, *recipients]`
  if `recipients`. Timeout 60 s.
- A failing channel is logged and appended to `.state/last_report.log`. It never
  changes the run status or exit code.
- `bn-backup notify set-smtp-password`: prompts with `getpass` and writes
  `password_file` (mode 0600, parent directories 0700).
- `bn-backup notify test`: sends "bn-backup test message" on every enabled
  channel and reports success or failure per channel (exit 1 if any failed).

Notifications are implemented in Phase 4, together with the run engine.

### 6.15 Scheduling (D-26)

`bn-backup schedule install (--weekly <mon..sun> | --daily) --at HH:MM`, `schedule show`,
`schedule remove`. `install` and `remove` are the only commands that run as
root: the operator calls them as `sudo "$(command -v bn-backup)" schedule install …`.
They take the operator from `$SUDO_USER` (refuse if it is unset or `root`) and
use that user's config path and executable path. Run without sudo they print
exactly that command line and exit 1. `schedule show` needs no sudo.

macOS: `/Library/LaunchDaemons/ar.bleiben.bn-backup.schedule.plist`
with `UserName <operator>`, `ProgramArguments [<absolute path of bn-backup>,
"-c", <absolute config path>, "run"]`,
`StartCalendarInterval {Weekday 0–6 (sun=0), Hour, Minute}` (omit `Weekday`
for daily), and `StandardOutPath`/`StandardErrorPath` set to
`<operator home>/Library/Logs/bn-backup-schedule.log`. Load it with
`launchctl bootstrap system`. Linux: `bn-backup-schedule.service` (with
`User=<operator>`) + `.timer` (`OnCalendar=Sun *-*-* 02:00:00`,
`Persistent=true`) in `/etc/systemd/system`, enabled and started. Only one
schedule exists at a time. `install` replaces it.

### 6.16 `runs list`, `runs show`, `runs cancel`

- **`runs list [--limit N] [--json]`** (default 20): reads `.state/history/*.json`,
  plus `.state/run.json` if it is newer and not yet in history. Newest first.
  Columns: run ID, status, attempts, green/total modules, first attempt,
  completed. An UNFINISHED run past its TTL is shown as EXPIRED.
- **`runs show RUN_ID [--json]`**: one run from history (or the current one):
  header as in the report, then every module with host, user, status,
  error_kind, reason, attempt, files and bytes transferred, and the path of its
  log under `logs/<run_id>/` if one exists. Unknown ID → exit 1.
- **`runs cancel`** (no run ID, D-35): if no run holds the lock → print "no run in
  progress", exit 1. Otherwise read the PID from the lock file (§6.8) and send SIGTERM
  (the run handles it exactly like Ctrl-C, §6.7). Wait up to 60 s for the lock to
  be released; report "cancelled; run <id> is UNFINISHED" and exit 0, or "still
  stopping" and exit 1. Works for scheduled runs too, because every run executes
  as the operator.

These are *run records*. In snapshot mode the old *data* lives in
`snapshots/<timestamp>/`, never inside `current/`.

### 6.17 Critical abort: a drive unplugged during a run (D-46)

A drive disappearing mid-run is critical. The run ends `ABORTED` and
everything staged is deleted, as if the backup had never happened. `current/`
is never touched.

**Triggers** (only while status is `RUNNING`):
- `source_drive_missing`: a job result contains a module with
  `error_kind: drive_missing`.
- `backup_volume_lost`: the `volume` server check fails on two consecutive
  poll cycles.

A drive that is not connected *before* the run is not an abort; the gate in
§6.7 step 5 reports NOT STARTED. A host that goes off the network mid-run is
not an abort either ("lost contact" → red → `UNFINISHED`).

**Procedure:**
1. Stop polling. Send `ctl stop` to every running job on every host, in
   parallel, best effort, at most 30 s.
2. If the backup volume is available: `rmtree .staging/` and recreate the
   per-user directories (§6.9 invariant); set `run.json` status `ABORTED` with
   the `abort` object and every non-green module `red` "aborted"; write history;
   write the report; notify; release the lock; exit 4.
3. If the backup volume is **not** available: write the abort marker
   `~/.local/state/bn-backup/abort-pending.json` (atomic; on the internal
   disk) with `{"run_id","cause","host","user","module","drive","at"}`; log to
   the server log file; notify (the report text is built in memory); release
   the lock; exit 4.

**Clean-up** (§6.7 step 2, only in `run`, only when the volume is back): if a
promotion journal existed and was just finished, the run is complete: delete
the marker and do nothing else. Otherwise `rmtree .staging/` and recreate the
per-user directories; if `run.json` has the marker's `run_id` and is not
`COMPLETE`, set it to `ABORTED` with the marker's data and write history;
delete the marker; log "cleaned up aborted run <id>". If the volume is still
missing, step 2 skips the clean-up, the server checks of step 3 fail (NOT
STARTED) and the marker stays.

After `ABORTED`, the next run is a new run: every module, cloned afresh from
`current/`.

### 6.18 CLI summary

```
bn-backup [-c CONFIG] [-v|-vv]
  server init
  server status [--json]
  config validate
  config migrate OLD.yml [-o NEW.yml]
  config show [--json]
  hosts list
  hosts add HOST [--address A] [--admin-user U] [--ssh-port P] [--no-bootstrap]
  hosts bootstrap [HOST] [--agent-package PATH]
  hosts configure [HOST]
  hosts remove HOST
  hosts forget HOST
  agent upgrade [HOST] [--agent-package PATH]
  agent status [HOST] [--json] [--no-wake]
  status [--json] [--no-wake]
  run [--dry-run] [--fresh] [--no-wake]
  runs list [--limit N] [--json]
  runs show RUN_ID [--json]
  runs cancel
  schedule install (--weekly DAY | --daily) --at HH:MM
  schedule show | schedule remove
  notify test
  notify set-smtp-password
  --version
```
Naming convention (D-33): `bn-backup <thing> <action>`; only `status` and `run`
are top-level. Any new command must follow it.

Logging with loguru: INFO by default, `-v` DEBUG, `-vv` TRACE. Also log to
`~/Library/Logs/bn-backup.log` (Linux: `~/.local/state/bn-backup/bn-backup.log`),
rotating at 10 MB with 5 kept.

---

## 7. Packaging and CI (D-06, D-08, D-29)

### macOS `.pkg` (release.yml, `macos-14` runner)
1. rsync: download `rsync-3.4.1.tar.gz` from `https://download.samba.org/pub/rsync/src/`,
   verify against `packaging/rsync/SHA256`, then build for arm64 and x86_64 with
   `./configure --disable-openssl --disable-xxhash --disable-zstd --disable-lz4 --disable-md2man`
   and `MACOSX_DEPLOYMENT_TARGET=13.0`. `lipo` the two builds into one universal file.
2. Agent: `cargo build --release` for both Apple targets, then `lipo`.
3. Assemble `BNBackupAgent.app`: `Contents/Info.plist` (`CFBundleIdentifier ar.bleiben.bn-backup-agent`,
   `CFBundleName BNBackupAgent`, `CFBundleExecutable bn-backup-agent`, `CFBundleShortVersionString <v>`,
   `LSUIElement true`, `LSMinimumSystemVersion 13.0`), `Contents/MacOS/bn-backup-agent`,
   `Contents/Resources/rsync`, and `Contents/Resources/rsync-COPYING` plus a
   `rsync-SOURCE.txt` with the source URL.
4. Ad-hoc sign the inner rsync, then the app: `codesign --force -s - …`.
5. `pkgbuild --identifier ar.bleiben.bn-backup-agent --version <v> --install-location / --scripts packaging/macos/scripts`.
   The `postinstall` script creates `/usr/local/bin` if needed, the symlink,
   and `$AH` (root, 0755). Nothing else.
6. The package is **not** Developer-ID-signed or notarized (D-07).

### Linux `.deb`
`cargo-deb` with musl targets (`cargo zigbuild` or `cross` for arm64). Package
`bn-backup-agent`, `Depends: rsync (>= 3.2.3), openssh-client, sudo`. Ships
`/usr/bin/bn-backup-agent` and `/lib/systemd/system/bn-backup-agent@.service`.
`postinst`: create `$AH`, run `systemctl daemon-reload`. `prerm` on remove: stop
running instances.

### Server
`uv build` → `bn_backup-<v>-py3-none-any.whl` (includes `vendor/rrsync` + license).
`pyproject.toml` metadata: description "bleiben Backup Orchestrator — local backups for
photographers and home studios"; `project.urls` Homepage and Repository =
`https://github.com/bleiben-labs/backup-orchestrator`.

### Release
Triggered by a `v*` tag. Fail if the tag ≠ the versions in `pyproject.toml` /
`Cargo.toml`. Upload the pkg, both debs, the wheel, **`rsync-3.4.1.tar.gz`**
(the exact verified tarball the build used, D-44) and `SHA256SUMS` (covering
all of them) to the GitHub release.

### ci.yml (push and PR)
Every job runs on **both** `ubuntu-latest` and `macos-14` unless §8 says
otherwise (D-53): ruff, mypy, pytest (server); cargo fmt --check, clippy, test
(agent); the platform tests and the two integration suites of §8.

---

## 8. Testing

The application is tested on macOS and on Linux, server and agent (D-53).

**Server unit tests** (pytest on ubuntu-latest and macos-14, with a fake
transport implementing the same interface as `agentctl.py`, plus a fake clock):
- config: every validation rule (including `.local` addresses and colliding
  generated host-config names), `config
  migrate` on v1's README example (and refusal of a v2 file), `config show`
  defaults, and `hosts add` keeping comments/order and rolling back on an
  invalid result.
- account rules: refuse root; refuse a user other than `receive_user`;
  `schedule install` without sudo prints the sudo command.
- runs: list/show over fixture history files; cancel against a fake lock holder.
- hosts remove: refuses while in config, unreachable host, no record.
- planner: new / resume / expired / reconciliation after config changes;
  EXPIRED keeps staging and marks every module pending (D-39); `--fresh`
  deletes staging; the TTL counts from `last_attempt_finished_at` and expires
  at exactly 30 h (≥).
- gate (D-45, D-49): any red row → NOT STARTED, exit 1, notification,
  `run.json` and staging byte-for-byte unchanged (new run and resume cases); a
  user not set up is red and nothing is configured; a leftover job is stopped,
  and red if it will not stop; `--fresh` with a red row leaves the UNFINISHED
  run and staging unchanged (D-57).
- lock (D-56): the lock lives on the internal disk; with the backup drive
  missing, `run` reports NOT STARTED (exit 1, notification), not exit 3;
  `status` never creates the lock file.
- staging preparation: after a `src_path` basename change, the old folder is
  not carried into staging; `hosts`/`motd` are cleared for host-config modules.
- dry run (D-51, D-56): no file under `backup_directory` is created, changed
  or deleted, except the `.probe/` folders under `.staging/<host>/<user>/`
  (compare a full tree listing with mtimes before and after), also
  when an EXPIRED-due run with staged data exists; no notification.
- abort (D-46): `drive_missing` in a job result → every job stopped, staging
  wiped, `ABORTED`, exit 4; volume lost → marker written, exit 4; next run with
  the volume back cleans up first; marker + finished promotion journal → no wipe.
- timeouts: `job_timeout_minutes: 0` never stops a long job; > 0 does (D-38).
- runner: all green → COMPLETE; one red → UNFINISHED; retry only red;
  timeout; lost contact; interrupted (SIGINT); a job that stops without a
  result (result file stuck at `running`, user not under `running`) → red,
  and the run does not hang; exit codes.
- promotion (D-52): mirror and snapshot. Simulate a crash after **every**
  step, then run recovery, and verify the same final tree **and** `run.json`
  `COMPLETE`, `last_complete.json` and history written. The module set keeps
  generated host-config folders in `current/`; folders outside it move to
  `removed/`, also with v1-style `*.yml` files in `current/`. Snapshot names:
  from `last_complete.json`, `00000000-000000-pre-v2` for a v1 backup, `-2`
  suffix on collision; pruning removes the oldest, including the pre-v2 one.
- server init: adopts a v1 tree (`previous/` → `removed/`), idempotent.
- keys: authorized_keys block regeneration preserves foreign lines.
- report and notification text; hint per `error_kind`; the "Files to check"
  section and subject suffix.
- status: read-only (no write anywhere except `.probe/`, D-56);
  lock-held behaviour (no probes).

**Agent unit tests** (cargo test on ubuntu-latest and macos-14): job
validation, rsync argv construction (no trailing slash, `--timeout`, never
`--checksum` in a transfer, option flags), verify-pass itemize parsing,
`drive_missing` detection for `/Volumes`, `/media`, `/run/media`, `/mnt`
(including a source folder that exists while its drive is not mounted),
`source_empty` with `expect_nonempty`, `server_mismatch` on submit,
classification table §5.10 including `server_denied`, a job stopping at the
first `drive_missing` with the rest `skipped`, `ssh-dispatch` allow-list and
quoting (hostile strings, empty string, stdin pass-through), the locked
authorized_keys line (replace, keep other lines), result JSON round-trip,
sudoers line, plist/unit rendering, host-config dotfile filter rules (a
deleted dotfile is deleted from the backup).

**Platform tests** (real OS facilities, no hosts):
- macos-14: create and attach a disk image formatted "Case-sensitive APFS"
  (`hdiutil`); run `clone.py` (`clonefile` of a tree, xattrs kept, metadata
  change on the clone does not touch the source), the `volume`,
  `apfs_case_sensitive`, `ownership` and `volume_writable` checks against it,
  and `plutil -lint` on every rendered plist.
- ubuntu-latest: create and mount a loopback Btrfs image (sudo); run
  `clone.py` (`cp --reflink=always`) and `volume_writable` on it, and on ext4
  to see the clear refusal; `systemd-analyze verify` on the rendered units.

**Linux integration** (`tests/integration/linux`, docker compose, ubuntu runner):
- `server`: Debian with python3.11, rsync 3.x, openssh-server, an operator
  account `operator`, the server installed from the local wheel,
  `BN_BACKUP_TEST_CLONE=copy` (containers have no reflink filesystem; real
  cloning is covered by the platform tests).
- `host1`, `host2`: Debian with systemd (use an image that runs systemd as PID 1),
  openssh-server, sudo, an admin user, users `alice` and `bob`, and the agent
  `.deb` built in the same CI job.
- Scenarios: bootstrap with passwords provided by `sshpass` in the test
  harness only; the control key cannot open a shell or `scp`; COMPLETE run;
  stop `host2` before a run → NOT STARTED and nothing staged; add a user to
  the config without `hosts configure` → NOT STARTED; make one `host2` module
  fail mid-run (an unreadable file) → UNFINISHED and current/ unchanged; fix it
  → re-run transfers only that module → COMPLETE; remove a module's source
  mount during a run (a tmpfs under `/mnt`) → ABORTED and staging empty;
  unmount that tmpfs while an empty folder with the source's path stays in
  its place → NOT STARTED with `drive_missing` and `current/` unchanged (D-55);
  restart `host1` during its job → its modules red, the run ends UNFINISHED; a
  module removed from config → moved to `removed/`; snapshot mode keeps N;
  `--dry-run` leaves the tree untouched; verify pass reports a file changed
  with the same size and mtime and overwrites nothing.

**macOS integration** (`tests/integration/macos`, macos-14 runner, one
machine): the server and the agent `.pkg` on the same runner, talking over SSH
to `localhost`; two extra local users created with `sysadminctl`; sources in
folders that macOS privacy protection does not cover (for example
`/Users/<user>/bn-src`); `backup_directory` and one source "photo drive" on
attached Case-sensitive APFS disk images. Scenarios: bootstrap (passwords
from the harness), COMPLETE, UNFINISHED → retry → COMPLETE, NOT STARTED,
ABORTED by detaching the source image mid-run, ABORTED by detaching the backup
image mid-run (marker, then clean-up), `schedule install` renders and loads.
If the hosted runner cannot do part of this (no SSH server, privacy protection
blocking the attached image), record exactly what failed in `docs/spikes.md`,
stop and ask the owner; the fallback is a self-hosted macOS runner (for example the owner's server).

**macOS manual checklist** (`docs/testing-macos.md`, Phase 6), for what needs a
person and Full Disk Access: FDA denied → status red with the right hint;
grant → green; backup a child account's `~/Documents` while that child is
logged out; upgrade → FDA re-prompt flow; "Allow full disk access for remote
users" off on the server → probe red with the `server_denied` hint; a
scheduled run after a reboot with nobody logged in; unplug the backup drive
mid-run; reboot mid-promotion (simulate by killing the process).

---

## 9. Behaviour kept from v1

- One failing module never stops the others (the one exception is a
  disconnected drive, D-46).
- Layout: `current/<module>/` with the v1 rsync semantics (source without
  trailing slash) and the host-config module `<user>-<host>/{hosts,motd,<user>/}`.
  v1's `previous/` lives on as `removed/`.
- `backup_report.log` with Successful / Failed sections and a `# Date:` line.
- `resume_backup` → `--partial`, `dry_run` → `--dry-run`.

Deliberately changed: `verify_backup` no longer adds `--checksum` to the
transfer; it is a report-only pass (D-50). A dry run no longer touches the
backup directory at all (D-51).

## 10. Code to port from v1

v1 is removed from `v2` in Phase 1. Read its sources from `main` when porting
(`git show main:src/backup_orchestrator/private/command_executor.py`, and so on).

- `command_executor.py`: `RSYNC_EXIT_CODES`, `_rsync_hint`, `_strip_usage`,
  `MAX_ERROR_LINES`. Move them to `report.py` (hints), and port the
  classification ideas to the agent's `classify.rs`.
- `backup_orchestrator.py`: `_move_missing_modules` semantics → promotion
  step "removed/"; `_write_report` format → `report.py`.
- Drop: `CommandExecutor.execute_command` live progress (agents run headless),
  `cProfile` option, hard-coded default YAML path.

---

## 11. Phases and acceptance criteria

Open one PR per phase into `v2`. Do not start a phase before the previous one
is merged, except that Phase 2 and Phase 3 may be developed in parallel after
Phase 1 (Phase 3 can only be *finished* after Phase 2, because its integration
tests need the agent package).

**Phase L — Licensing on `main` (D-47), before anything else.** One pull
request from branch `licensing` into `main` with: `LICENSE`, `LICENSING.md`,
`TRADEMARKS.md`, `CLA.md`, `CONTRIBUTING.md`, `.github/workflows/cla.yml`, a
"License" section in the existing README, and v1's `setup.py` changed from
`license="Proprietary"` to `license="PolyForm-Noncommercial-1.0.0"` (v1 is
relicensed too). No other v1 change. *Done when:* the owner has approved the
texts (§13) and merged the PR. Then create `v2` from `main`.

**Phase 0 — Spikes (macOS + Linux, manual, results in `docs/spikes.md`).**
Each spike states pass/fail with evidence (commands + output). **Any fail → stop and ask the owner.**
- S1: an ad-hoc-signed Rust binary in an `.app`, granted FDA, started by a
  LaunchDaemon with `UserName=<other user>`, can read that user's `~/Documents`
  through a spawned bundled rsync. Without FDA it gets `EPERM`.
- S2: `launchctl kickstart system/<label>` issued through the locked control
  key (sshd *without* "Allow full disk access for remote users" on that host)
  still lets S1 read `~/Documents`.
- S3: vendored rrsync 3.4.1 with `-wo` accepts every server-side option the
  agent sends (§5.9: `-M--fake-super`, `--delete`, `--xattrs`, `--hard-links`,
  `--numeric-ids`, `--timeout`, `--partial`, `--checksum --dry-run`,
  `--dry-run`). It refuses reads. The fake-super xattr is present on the
  received files on APFS.
- S4: rebuilding the agent (new cdhash) loses the FDA grant. Reinstalling the
  identical binary keeps it.
- S5: an unsigned pkg copied by `scp` installs with `sudo installer -pkg … -target /` over SSH.
- S6: `clonefile()` on a directory on an external APFS volume clones the tree
  and keeps the rsync fake-super xattrs. A later metadata change on the clone
  does not affect the source.
- S7: `signal-cli -a <acct> send --note-to-self -m "…"` delivers to Note to Self
  on a linked device.
- S8: `/etc/sudoers.d/` drop-ins are honoured on macOS 13+.
- S9: `launchctl print system/<label>` shows a usable `state =` field for
  running/not running.
- S10 (D-54): on the server Mac, a Python process running as the operator can
  create, `clonefile` and delete files on the external APFS volume (a) when
  started from Terminal and (b) when started by a LaunchDaemon with
  `UserName=<operator>` after a reboot with nobody logged in. Record any
  consent prompt in (a) and any denial in (b).
- S11 (D-54): after a reboot with nobody logged in, is the external volume
  mounted? If not, test whether
  `sudo defaults write /Library/Preferences/SystemConfiguration/autodiskmount AutomountDisksWithoutUserLogin -bool true`
  makes it mount, and record the result.
- S12 (D-48): the locked control-key line of §5.11 works on macOS 13+ and
  Debian 12: `ctl ping` answers, stdin reaches `ctl submit`, an argument with
  spaces and quotes arrives intact, and a plain login, `scp` and port
  forwarding are refused.
- S13: with "Allow full disk access for remote users" off on the server, a
  push fails and its error line carries a `[receiver]` or `[generator]` tag
  (§5.10), also when the sender is the bundled rsync 3.4.1.
- S14 (D-50): for two files with the same size and mtime but different
  content, `rsync --checksum --dry-run --out-format='%i %n'` prints an itemize
  string with `c` set and `s`, `t` unset, and transfers nothing.

**Phase 1 — Repo restructure + config.** Remove the v1 package at once: it is
incompatible with v2 and stays available on `main`. Then: license headers and
package license metadata (§13 item 2), `THIRD_PARTY_NOTICES.md`, monorepo
skeleton, CI skeleton, `config.py` with validation, `config migrate`,
`config show`, `config validate`. The README gets a one-paragraph "v2 in
development" notice (the full README is Phase 7). *Done when:* config unit
tests pass on both platforms; v1 files are gone; CI is green.

**Phase 2 — Agent.** All of §5, plus the macOS and Linux packaging scripts
(buildable locally). *Done when:* agent unit tests pass on ubuntu and macOS
runners, and the `.deb` installs in a container where `ctl info` works.

**Phase 3 — Server foundations.** `server init`, both SSH connections,
`agentctl.py`, keys, `releases.py` (use `--agent-package` until a release
exists), `hosts list/add/bootstrap/configure/remove/forget`, `agent upgrade`,
`status`, `server status`, `agent status`. *Done when:* the Linux integration
bootstrap, control-key and status scenarios pass.

**Phase 4 — Run engine and notifications.** `runner.py`, `clone.py`,
`promotion.py`, lock, `report.py`, `notify/` with `notify test` and
`notify set-smtp-password`, `runs list/show/cancel`. *Done when:* every
runner, gate, dry-run, abort and promotion unit test in §8 passes, the
platform tests pass on both runners, `notify test` works against a local SMTP
debug server, and the Linux integration run scenarios pass.

**Phase 5 — Wake and scheduling.** *Done when:* unit tests for the magic
packet bytes and plist/timer rendering pass on both platforms.

**Phase 6 — Release pipeline + platform validation.** `release.yml` produces
all artifacts on a test tag in a fork or with `workflow_dispatch`. The macOS
integration suite (§8) runs in CI. Write `docs/testing-macos.md` and have the
owner run it. *Done when:* both integration suites are green and the owner
confirms the checklist.

**Phase 7 — Docs.** New README for **bleiben Backup Orchestrator**, written
for photographers first (D-37): a short "why" (local, private, fast restores;
complements cloud; the 3-2-1 rule), then install the server, `server init`,
bootstrap, status, run, schedule, notifications, upgrade, restoring files from
`current/`, troubleshooting by error_kind. Include a "For photographers"
section: one module per archive, external drives as sources (connect them
before a run, never unplug during one), close Lightroom Classic / Capture One
/ Photos before a run, exclude `*.lrdata` previews, snapshot mode recommended,
`verify_backup` now and then. Repository links point to
`github.com/bleiben-labs/backup-orchestrator`. *Done when:* the owner approves.

**Phase 8 — Merge and release (D-47).** Tag the last v1 commit on `main` as
`v1-final` (ask the owner to push the tag, or push it when they say so). Open
one pull request `v2` → `main` containing server and agent together. After the
owner merges it, the owner (or you, on their instruction) tags `v2.0.0`; the
release workflow publishes the artifacts. *Done when:* the `v2.0.0` release
exists with every file of §7.

---

## 12. Do not

- Do not keep going after a drive disappears mid-run, and do not keep anything
  in `.staging/` after an abort (D-46).
- Do not start a run while any row of the board is red (D-45).
- Do not back up an external-drive path unless its drive is really mounted,
  and do not send an empty source over a backup that holds data (D-55).
- Do not run `bn-backup-agent run` over SSH, or read user files from `ctl`.
- Do not add passwordless sudo for anything except `ctl *` on hosts. The server
  machine gets no sudoers rule, no wrapper and no extra account.
- Do not use the control key for anything but `ctl` commands, and never give it
  a shell: install, upgrade and removal go through the operator connection.
- Do not let `status` or a dry run write anything (D-49, D-51).
- Do not let `verify_backup` overwrite a file (D-50).
- Do not use hard links for staging or snapshots.
- Do not write into `current/` except during promotion.
- Do not use `--compress`, `--inplace` or `--append` in rsync.
- Do not add Developer ID signing, notarization, MDM profiles, a web UI, a
  restore command or Docker support. They are future scope.
- Do not require Homebrew on source Macs.
- Do not store secrets in the config file. The SMTP password lives in `password_file`.
- Do not change, reword or "simplify" the PolyForm license text, and do not add
  any revenue number or condition to `LICENSE`. Policy lives only in `LICENSING.md`.
- Do not merge outside contributions unless the CLA check has passed.

---

## 13. Licensing (D-41…D-44)

Not legal advice: the owner may have `LICENSING.md` and `CLA.md` reviewed by a
lawyer. Draft them exactly as specified in Phase L, then ask the owner to
approve them before the licensing PR is merged into `main`.

**Copyright holder:** Ariel Hernandez, working as bleiben, always written
`Ariel Hernandez (bleiben)`. A brand alone cannot hold copyright, so the notice
names the person and the brand together. Ask the owner to confirm the exact
spelling of their legal name before the licensing PR is merged. **Contact:** `https://www.bleiben.ar` only. No
email address appears anywhere in the repository; people reach the owner
through the website.

1. **`LICENSE`**: the official text of PolyForm Noncommercial License 1.0.0,
   copied verbatim from `https://polyformproject.org/licenses/noncommercial/1.0.0/`
   (download it; do not retype it from memory), preceded by:
   ```
   Required Notice: Copyright (c) 2018-2026 Ariel Hernandez (bleiben, https://www.bleiben.ar)
   ```
2. **SPDX identifier** everywhere: `PolyForm-Noncommercial-1.0.0`.
   - Every source file you write (Python, Rust, shell, YAML workflows) starts
     with `SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0` and
     `Copyright (c) 2018-2026 Ariel Hernandez (bleiben)` as comments. Not on vendored files.
   - `server/pyproject.toml`: `license = "PolyForm-Noncommercial-1.0.0"`,
     `license-files = ["LICENSE", "LICENSING.md", "THIRD_PARTY_NOTICES.md"]`.
   - `agent/Cargo.toml`: `license = "PolyForm-Noncommercial-1.0.0"`,
     `publish = false`.
   - `.deb`: `debian/copyright` in machine-readable format (DEP-5) naming
     PolyForm-Noncommercial-1.0.0 for our files; installed docs include
     `LICENSE`, `LICENSING.md` and `THIRD_PARTY_NOTICES.md` under
     `/usr/share/doc/bn-backup-agent/`.
   - macOS `.pkg`: the same three files in `BNBackupAgent.app/Contents/Resources/`,
     next to `rsync-COPYING` and `rsync-SOURCE.txt`.
3. **`LICENSING.md`** (plain language, for photographers; headings in this order):
   - *Free for noncommercial use*: personal, hobby and family use, education,
     charities, research — under PolyForm Noncommercial 1.0.0.
   - *Commercial use needs a license*: including a freelance or professional
     photographer backing up paid work, studios and companies. Contact
     through www.bleiben.ar.
   - *Free commercial licenses for small earners*: freelance photographers with
     less than A$80,000 a year in gross income from photography receive a
     commercial license free of charge on request. Above that, the license is
     paid; terms on request. Every license is confirmed in writing by email.
     This is a policy of bleiben, not part of the license text, and may change;
     licenses already granted keep their terms.
   - *Not allowed without a written agreement*: selling the software, including
     it in another product, or offering it as a service.
   - *Third-party software*: rsync and rrsync are GPLv3 and are not restricted by
     this policy (see `THIRD_PARTY_NOTICES.md`).
   - *Trademarks*: see `TRADEMARKS.md`.
4. **`TRADEMARKS.md`**: "bleiben" and the bleiben logo are trademarks of Ariel Hernandez.
   The license does not grant rights to them. Forks or modified versions must not
   use the bleiben name or logo, and must not suggest endorsement by bleiben.
   Unmodified copies may say what they are.
5. **`THIRD_PARTY_NOTICES.md`**: generated in CI from the actual dependency trees
   (`cargo about` or `cargo-license` for Rust; `pip-licenses` for Python) plus a
   hand-written section for rsync 3.4.1 and rrsync: GPL-3.0-or-later, where the
   full license text is, and that the exact source is attached to every release
   as `rsync-3.4.1.tar.gz`. CI fails if a dependency's license is not one of
   MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, Unicode-3.0, Zlib,
   MPL-2.0 or PSF-2.0; ask the owner before adding anything else.
6. **`CLA.md`**: the Apache Software Foundation Individual Contributor License
   Agreement v2.2, adapted: "the Foundation" → "Ariel Hernandez (bleiben)";
   remove ASF-specific references; keep the copyright and patent license grants,
   including the copyright holder's right to sublicense under any terms (so commercial licenses remain possible).
   Mark the file "Draft — pending owner review" until the owner approves.
7. **`CONTRIBUTING.md`**: how to build and test, the coding rules of this file,
   and that every outside contributor must sign `CLA.md` once (by commenting
   the sentence the bot asks for on their first pull request).
8. **CLA check** (part of Phase L, so the workflow is on the default branch,
   where it must be to run): add `.github/workflows/cla.yml` using
   `contributor-assistant/github-action` (pin a released version), storing
   signatures in `signatures/cla.json` on a `cla-signatures` branch, allowlisting
   the owner and bots. It must be a required check on `v2` and `main` (the owner
   enables branch protection; tell them).
9. **README**: a short "License" section linking `LICENSE`, `LICENSING.md` and
   `TRADEMARKS.md`, with one sentence: "Free for personal and noncommercial use;
   photographers using it for paid work, contact bleiben — small earners get a
   free license."
