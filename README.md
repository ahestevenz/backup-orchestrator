# bleiben Backup Orchestrator

**Local backups for photographers and home studios.** One always-on computer
at home, the server, with an external drive keeps a copy of the photo archives, catalogs and documents of
every Mac and Linux computer at home, and tells you plainly when something
needs attention.

## Why a local backup

For a photographer, the archive *is* the body of work: a lost drive can mean
years of shoots that cannot be taken again.

- **Private.** Your files stay in your house, on a drive you own.
- **Fast to restore.** Copying a folder back from a drive on your own network
  takes minutes, not days of downloading.
- **It complements the cloud, it does not replace it.** Follow the 3-2-1 rule:
  three copies, on two kinds of storage, one of them away from home. Keep a
  copy of the backup drive somewhere else too.

## How it works

The **server** (`bn-backup`, a Python program) runs on a computer that is
always on (a Mac or a Debian-based Linux machine), with an external drive. Every computer being backed up runs a
small **agent** (`bn-backup-agent`), which reads each person's files *as that
person* and sends them to the server. That is why macOS privacy protection
no longer gets in the way: the agent holds Full Disk Access, which you grant
once on each Mac.

A backup counts only when every computer succeeded. The new copy is built in
a separate work area, and replaces the last complete backup only when every
part is in; if anything fails, your last complete backup is untouched and
the next run redoes only what failed.

The full design, with the reasoning behind every choice, is in
[`docs/design.md`](docs/design.md).

## What you need

- A **server**: a Mac (macOS 13 or later) or a Debian-based Linux computer that
  stays on, with an **external drive** for the backup, formatted
  **APFS (Case-sensitive)** on a Mac, or **Btrfs** or **XFS** on Linux.
- Macs with macOS 13 or later, and Debian-based Linux computers.
- A home network where the computers can reach each other by name
  (`galactica.home.lan`, `galactica.local`) or IP address.
- Optional: an email account (app password) and/or Signal for notifications.

## Install

### 1. The server

These steps are for a Mac server. On a Debian-based Linux server, format the
backup drive as Btrfs or XFS, run `sudo apt install rsync openssh-server`,
install [uv](https://docs.astral.sh/uv/), then continue at step 4.

1. Format the backup drive as **APFS (Case-sensitive)**. In Finder → Get Info,
   make sure *Ignore ownership on this volume* is **off**.
2. Turn on *System Settings → General → Sharing → Remote Login*, and in its
   ⓘ turn on **Allow full disk access for remote users**.
3. Install [Homebrew](https://brew.sh), then:
   ```sh
   brew install rsync uv          # and signal-cli for Signal notifications
   ```
4. Install the server from the latest release:
   ```sh
   uv tool install https://github.com/bleiben-labs/backup-orchestrator/releases/download/v2.0.0/bn_backup-2.0.0-py3-none-any.whl
   ```
5. Run `bn-backup server init`. The first time it writes a config template to
   `~/.config/bn-backup/config.yml`. Edit it (see below), then run
   `bn-backup server init` again. If you used version 1, your existing backup
   is adopted, so the first v2 run copies only what changed.

### 2. Each computer to back up

- **Mac:** turn on *Remote Login* and allow your admin account. Nothing else.
- **Linux:** make sure `openssh-server` is installed and your admin account can use `sudo`.

### 3. Set up every computer, from your desk

```sh
bn-backup hosts bootstrap
```

It installs the agent on every computer in the config. You type each
computer's admin password at your desk. On each **Mac**, someone then switches
on **BNBackupAgent** in *System Settings → Privacy & Security → Full Disk
Access* at that Mac (macOS only lets a person at the screen do this). The
server waits and carries on by itself.

## The configuration

```yaml
version: 2

server:
  backup_directory: /Volumes/Backup/bn-backup
  ssh_host: server.home.lan        # how the computers reach the server
  receive_user: ariel               # your account on the server

settings:
  mode: snapshot                    # keep earlier versions (recommended)
  snapshot_keep: 8

hosts:
  galactica:
    address: galactica.home.lan
    admin_user: ariel

modules:
  photo-archive:                    # RAW archive on an external drive
    host: galactica
    user: ariel
    src_path: /Volumes/PhotoArchive/Photos
  lightroom:                        # close Lightroom before a run
    host: galactica
    user: ariel
    src_path: /Users/ariel/Pictures/Lightroom
    excludes: ["*.lrdata"]          # previews: large, rebuilt by Lightroom
```

`bn-backup config validate` checks it and lists every problem;
`bn-backup config show` prints it with every default filled in. A version 1
file can be converted with `bn-backup config migrate OLD.yml -o NEW.yml`.

## For photographers

- **One module per archive.** A RAW archive, a catalog folder and an exports
  folder each make a good module; smaller modules retry faster.
- **External drives are fine as sources.** Connect them *before* a run. If a
  drive is not connected, the backup does not start and tells you which one.
  **Never unplug a drive during a run**: the run is then aborted and the next
  one starts from zero (your last complete backup stays safe). An empty
  folder where a drive is normally mounted is never mistaken for your archive.
- **Close Lightroom Classic, Capture One or Photos before a run.** Catalogs
  are databases; a copy taken while they are open may be inconsistent.
- **Exclude previews** such as Lightroom's `*.lrdata`; they are large and
  rebuilt automatically.
- **Use snapshot mode.** It keeps the last `snapshot_keep` complete backups,
  so a photo deleted or overwritten by mistake can still be found.
- **Check for silent corruption now and then** with `verify_backup: true`.
  The run then compares every file's contents with its backup and lists files
  that differ although date and size match. Nothing is overwritten; you
  decide which copy is good.

## Everyday use

| Command | What it does |
| --- | --- |
| `bn-backup status` | The board: would a backup start and succeed right now? One green or red row per person and computer, with the reason |
| `bn-backup run` | Back up. Exit code 0: complete; 2: some parts failed (re-run within 30 hours to finish only those); 1: not started (see the board); 4: aborted (a drive was unplugged) |
| `bn-backup run --dry-run` | Check everything without changing anything |
| `bn-backup runs list` / `runs show RUN_ID` | Past runs and their details |
| `bn-backup runs cancel` | Stop the run in progress |

### Schedule

```sh
sudo "$(command -v bn-backup)" schedule install --weekly sun --at 02:00
bn-backup schedule show
sudo "$(command -v bn-backup)" schedule remove
```

### Notifications

In the config, under `notifications:`, enable `email` (SMTP with an app
password, stored with `bn-backup notify set-smtp-password`) and/or `signal`
(`signal-cli` linked to your phone once with `signal-cli link`; messages
arrive in *Note to Self*). `bn-backup notify test` sends a test message.

### Adding a computer or a person later

- A new computer: `bn-backup hosts add HOST` (asks for the details, writes the
  config, sets it up), or add it to the config and run `bn-backup hosts bootstrap HOST`.
- A new person on a known computer: add their modules, then
  `bn-backup hosts configure HOST`. Until then their row is red.
- Stop backing something up: delete it from the config; it moves to
  `removed/` after the next complete run.

### Updating

```sh
uv tool install --force <link to the new wheel>
bn-backup agent upgrade
```

Linux computers update without anyone at the machine. On each Mac, switch
BNBackupAgent on again in Full Disk Access after an agent update; the server
tells you where.

## Restoring files

Open the backup drive on the server (in Finder on a Mac): the last complete backup is
in `current/<module>/`, earlier versions are in `snapshots/<date>/<module>/`
(snapshot mode), and modules you stopped backing up are in `removed/`. Copy
what you need back to its computer. The files' original owners and
permissions are recorded in the backup, so a future `bn-backup restore`
command can put them back exactly.

## When something is red

| Reason | What to do |
| --- | --- |
| `tcc` | Switch on BNBackupAgent in Full Disk Access on that Mac |
| `server_denied` | On a Mac server, turn on *Allow full disk access for remote users* (Remote Login → ⓘ), and check the drive is not read-only |
| `drive_missing` | Connect the external drive named in the message, then run again |
| `source_empty` | The folder is empty but its backup is not. Connect the drive that belongs there; if you emptied it on purpose, remove the module from the config |
| `missing` | The folder does not exist; check `src_path` in the config |
| `permission` | That person cannot read some files; fix their ownership or exclude them |
| `network` | That computer could not reach the server; check the network and the names |
| `stalled` | No progress for 10 minutes; check the network or a sleeping drive |
| unreachable | The computer is asleep or off. Wake-on-LAN is tried automatically; computers that are shut down usually cannot be woken |
| `hosts configure` | A new person in the config: run `bn-backup hosts configure HOST` |

Each failure in the report and the notification comes with its own hint.

## License

Free for personal and noncommercial use; photographers using it for paid work, contact bleiben — small earners get a free license.

- [`LICENSE`](LICENSE): PolyForm Noncommercial License 1.0.0
- [`LICENSING.md`](LICENSING.md): who may use it for free, and commercial licenses
- [`TRADEMARKS.md`](TRADEMARKS.md): the bleiben name and logo

rsync and rrsync, which ship with the software, are GPLv3; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Source and releases: [github.com/bleiben-labs/backup-orchestrator](https://github.com/bleiben-labs/backup-orchestrator).
Contributions are welcome; see [`CONTRIBUTING.md`](CONTRIBUTING.md).
