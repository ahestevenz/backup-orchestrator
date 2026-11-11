# Manual macOS checklist

Some things only a person at a Mac can test: Full Disk Access is granted by
clicking, privacy protection behaves differently for each account, and
reboots involve the login window. Run this checklist on your real machines
before each release that changes the agent or the server's run engine
(CLAUDE.md §8, Phase 6). Record the date, the version and the result of each
item at the bottom.

**Machines:** the Mac mini (server, with the backup drive) and one source Mac
with a child account (the examples use `athena` and `sofia`). The server is
installed and `bn-backup status` is green before you start.

## 1. Full Disk Access denied, then granted

1. On the source Mac: System Settings → Privacy & Security → Full Disk Access
   → switch **BNBackupAgent** off.
2. On the Mac mini: `bn-backup status`.
   **Expect:** the `athena/sofia` row is red with
   "Switch on BNBackupAgent in Full Disk Access on athena".
3. Switch it back on; run `bn-backup status` again.
   **Expect:** green.

## 2. A child's Documents while the child is logged out

1. Put a file in `sofia`'s `~/Documents`, then log `sofia` out completely.
2. Make sure a module backs up `/Users/sofia/Documents`, then `bn-backup run`.
   **Expect:** COMPLETE, and the file is in
   `current/sofia-documents/Documents/` on the backup drive.

## 3. Agent upgrade: the Full Disk Access re-prompt

1. Install a newer server version on the Mac mini (or reinstall the same
   version's wheel built from a changed agent), then `bn-backup agent upgrade athena`.
   **Expect:** the package installs over SSH with your password; the server
   says "Go to athena and switch on BNBackupAgent…" and System Settings opens
   on athena if someone is logged in there.
2. Switch BNBackupAgent on at athena (remove and re-add it if the switch
   looks on but the probe stays red, and note which it was).
   **Expect:** the upgrade finishes by itself within 15 seconds.

## 4. The Mac mini refuses the write

1. On the Mac mini: System Settings → General → Sharing → Remote Login → ⓘ →
   turn **"Allow full disk access for remote users" off**.
2. `bn-backup status`.
   **Expect:** red, with the hint to turn that setting back on (`server_denied`).
3. Turn it back on. **Expect:** green.

## 5. A scheduled run after a reboot with nobody logged in

1. `sudo "$(command -v bn-backup)" schedule install --daily --at <5 minutes from now>`.
2. Restart the Mac mini and do **not** log in. With FileVault on, use
   `sudo fdesetup authrestart` so the disk unlocks without a login.
3. After the scheduled time, from another computer:
   `ssh <you>@<mac mini> ~/.local/bin/bn-backup runs list`.
   **Expect:** a new run that is COMPLETE. If the backup drive was not mounted,
   see spike S11 (`AutomountDisksWithoutUserLogin`).
4. `sudo "$(command -v bn-backup)" schedule remove`.

## 6. The backup drive unplugged during a run

1. Start `bn-backup run` with enough new data that it takes a minute or more.
2. Unplug the backup drive while it runs.
   **Expect:** within about 20 seconds the run stops with exit code 4 and an
   "ABORTED — backup drive unplugged" notification; `bn-backup status` notes
   "clean-up pending".
3. Plug the drive back in, then `bn-backup run`.
   **Expect:** "cleaned up aborted run …", then a run that starts from zero
   and completes. `current/` still holds the previous complete backup throughout.

## 7. A reboot during promotion

Promotion is quick, so simulate the crash: start `bn-backup run`, and the
moment the output shows the report is being written, kill the process
(`pkill -9 -f "bn-backup run"`).

**Expect:** `bn-backup status` shows "promotion interrupted" red; the next
`bn-backup run` says "finishing an interrupted promotion", sends that run's
notification with "(finished after an interruption)", and then works normally.
If the kill came too early or too late, repeat; any outcome other than a
complete, consistent `current/` is a failure.

## Results

| Date | Version | Item | Result | Notes |
| --- | --- | --- | --- | --- |
| | | 1 | | |
| | | 2 | | |
| | | 3 | | |
| | | 4 | | |
| | | 5 | | |
| | | 6 | | |
| | | 7 | | |
