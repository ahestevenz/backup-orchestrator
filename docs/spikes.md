# Phase 0 — Spikes

Fourteen hands-on experiments on your own machines. Each one tests an
assumption the v2 design depends on (CLAUDE.md §11, Phase 0). Nothing here
is v2 code: the helpers in [`spikes/`](spikes/) are throwaway and get deleted
after Phase 0.

**Rule: any FAIL stops the project.** Record the evidence (the commands and
their output), then bring it back before any v2 code is written. A failure is
not a disaster; it means the design changes before the code does.

## Summary

| Spike | What it proves | Machine | Result |
| --- | --- | --- | --- |
| S1 | An ad-hoc-signed agent started by launchd as another user reads that user's `~/Documents` through its bundled rsync once it has Full Disk Access, and is refused without it | Source Mac | pending |
| S2 | Starting that job through the locked control key works without "Allow full disk access for remote users" | Source Mac | pending |
| S3 | rrsync 3.4.1 with `-wo` accepts every option the agent sends, refuses reads, and the fake-super attribute lands on APFS | Mac mini | pending |
| S4 | A new agent build loses Full Disk Access; reinstalling the identical build keeps it | Source Mac | pending |
| S5 | An unsigned `.pkg` copied by `scp` installs with `sudo installer` over SSH | Source Mac | pending |
| S6 | `clonefile()` clones a folder tree on the backup drive, keeps the fake-super attributes, and the clone's metadata is independent | Mac mini | pending |
| S7 | `signal-cli` delivers to Note to Self on a linked device | Mac mini | pending |
| S8 | `/etc/sudoers.d/` drop-ins are honoured | Source Mac | pending |
| S9 | `launchctl print` shows a usable `state =` field | Source Mac | pending |
| S10 | Python running as you can create, clone and delete on the backup drive, from Terminal and from a LaunchDaemon after a reboot with nobody logged in | Mac mini | pending |
| S11 | The backup drive is mounted after a reboot with nobody logged in | Mac mini | pending |
| S12 | The locked control key passes commands, quotes and stdin intact, and refuses a shell, `scp` and port forwarding | Source Mac and Debian 12 | pending |
| S13 | With "Allow full disk access for remote users" off on the Mac mini, the push error carries a `[receiver]` or `[generator]` tag | Mac mini | pending |
| S14 | `--checksum --dry-run` flags a file whose content changed while size and date stayed the same, and transfers nothing | Mac mini | pending |

### Already checked on the development Mac (not a substitute)

These ran on the Mac this plan was written on, with a disk image standing in
for the backup drive. They only lower the risk; every spike still runs on
your real machines.

- rsync 3.4.1 builds with the release `configure` options and links only to
  macOS system libraries, so the bundled copy needs nothing from Homebrew.
- The spike app, packaged by `make-app.sh --pkg`, is marked non-relocatable,
  and its signature still verifies after unpacking.
- The Full Disk Access check (opening the system TCC database) reports
  `denied` from a Terminal without Full Disk Access.
- `clone_test.py` passes on a Case-sensitive APFS disk image, with rsync's
  `rsync.%stat` attribute (the macOS name of the fake-super attribute).
- The control-key line written by `setup-control.sh` matches CLAUDE.md §5.11.

## 0. Preparation

### 0.1 Machines and settings

| Machine | Needs |
| --- | --- |
| **Source Mac** (`TESTMAC`) | macOS 13 or later. *Remote Login* on, and inside its ⓘ **"Allow full disk access for remote users" OFF** (S2 depends on it). Xcode Command Line Tools (`xcode-select --install`) and Rust ([rustup.rs](https://rustup.rs)) |
| **Mac mini** (`SERVER`) | The backup drive connected (APFS, Case-sensitive). *Remote Login* on, with **"Allow full disk access for remote users" ON** (off only during S13). Homebrew, then `brew install rsync signal-cli qrencode uv` |
| **Debian 12 host** (`LINUXHOST`) | `openssh-server` and `sudo` installed; your admin account in the `sudo` group |

### 0.2 Edit the settings and copy the kit

1. Edit [`spikes/spike.env`](spikes/spike.env) on this computer: host names,
   your account names, the backup drive's path.
2. Copy the kit to each machine, from the repository folder. On the
   machines, keep it out of Desktop, Documents and Downloads, which macOS
   protects:

   ```sh
   . docs/spikes/spike.env
   scp -r docs/spikes "$ADMIN@$TESTMAC:bnspike-kit"
   scp -r docs/spikes "$OPERATOR@$SERVER:bnspike-kit"
   scp -r docs/spikes "$ADMIN@$LINUXHOST:bnspike-kit"
   ```

3. On each machine, run every command below from inside the kit after loading
   the settings: `cd ~/bnspike-kit && . ./spike.env`

### 0.3 A test user on the source Mac

The spikes back up a throwaway account, never a real family member's.

1. `sudo sysadminctl -addUser bntest -fullName "BN Spike" -password -`
   (it asks for the new password).
2. At the Mac, log in once as **BN Spike**. Open TextEdit, save a file named
   `spike.txt` in **Documents**, then log out completely (Apple menu → Log Out).

### 0.4 The control key (on the Mac mini)

```sh
ssh-keygen -t ed25519 -N "" -C bnspike-control -f ~/.ssh/bnspike_control
scp ~/.ssh/bnspike_control.pub ADMIN@TESTMAC:
scp ~/.ssh/bnspike_control.pub ADMIN@LINUXHOST:
```

## A. The source Mac

Run on the source Mac, in Terminal, as the admin account.

### A.0 Build the spike app

```sh
./build-rsync.sh      # downloads rsync 3.4.1, checks its fingerprint, builds it
./make-app.sh         # builds BNSpike.app, signs it ad hoc, installs it in /Applications
```

`make-app.sh` prints the app's `CDHash`. Note it down for S4.

### S1 — Full Disk Access through launchd, as another user

1. Install the job that runs as `bntest`. It checks access, then copies
   `bntest`'s Documents with the bundled rsync:

   ```sh
   sudo ./install-daemon.sh bntest bntest -- \
     /Applications/BNSpike.app/Contents/MacOS/bnspike probe /Users/bntest/Documents \
     -- -a /Users/bntest/Documents /Users/Shared/bnspike/out-bntest/
   ```

2. **Without Full Disk Access** (BNSpike must not be in the list yet):

   ```sh
   sudo launchctl kickstart system/ar.bleiben.bnspike.bntest
   sleep 5; cat /Users/Shared/bnspike/bntest.log
   ```

   Expect `user: bntest`, `fda: denied (Operation not permitted …)`,
   `read /Users/bntest/Documents: error (Operation not permitted …)` and a
   non-zero `rsync exit`.

3. **Grant it:** System Settings → Privacy & Security → Full Disk Access →
   **+** → choose `/Applications/BNSpike.app` (press ⌘⇧G to type the path) →
   switch it on.
4. Run step 2 again. Expect `fda: granted`, `read …: ok`, `rsync exit: 0`, and
   `ls /Users/Shared/bnspike/out-bntest/Documents/` lists `spike.txt`.

**Pass when** step 2 is refused and step 4 succeeds, both while `bntest` is
logged out.

**Result:** pending

```text
(paste both log runs here)
```

### S4 — Full Disk Access after an update

1. **Identical reinstall:**

   ```sh
   codesign -dvvv /Applications/BNSpike.app 2>&1 | grep CDHash
   sudo ditto /Applications/BNSpike.app /Users/Shared/bnspike/BNSpike-copy.app
   sudo rm -rf /Applications/BNSpike.app
   sudo ditto /Users/Shared/bnspike/BNSpike-copy.app /Applications/BNSpike.app
   codesign -dvvv /Applications/BNSpike.app 2>&1 | grep CDHash
   sudo launchctl kickstart system/ar.bleiben.bnspike.bntest; sleep 5
   tail -8 /Users/Shared/bnspike/bntest.log
   ```

   Expect the same CDHash twice and `fda: granted`.

2. **New build:** in `bnspike/src/main.rs` change `BUILD_TAG` to `"build-2"`,
   then `./make-app.sh` and run the kickstart and `tail` lines again. Expect a
   different CDHash and `fda: denied`. Also note what System Settings shows
   for BNSpike now (switched on, off, or listed twice).
3. Switch BNSpike on again in Full Disk Access (remove and re-add it if the
   switch does not help), and record what it took. Later spikes need it on.

**Pass when** step 1 keeps the grant and step 2 loses it.

**Result:** pending

```text
(CDHashes, log lines, what System Settings showed)
```

### S9 — Is the job running?

```sh
sudo ./install-daemon.sh bntest bntest -- \
  /Applications/BNSpike.app/Contents/MacOS/bnspike probe /Users/bntest/Documents --hold 60
sudo launchctl kickstart system/ar.bleiben.bnspike.bntest
sudo launchctl print system/ar.bleiben.bnspike.bntest | grep -E '^\s+(state|pid) ='
sleep 65
sudo launchctl print system/ar.bleiben.bnspike.bntest | grep -E '^\s+(state|pid) ='
# stopping a running job, like "ctl stop":
sudo launchctl kickstart system/ar.bleiben.bnspike.bntest; sleep 2
sudo launchctl kill SIGTERM system/ar.bleiben.bnspike.bntest; sleep 2
sudo launchctl print system/ar.bleiben.bnspike.bntest | grep -E '^\s+state ='
tail -4 /Users/Shared/bnspike/bntest.log
```

**Pass when** the first check shows `state = running` with a pid, the second
`state = not running`, and after the SIGTERM the state is `not running` and
the log's last run has no `done` line.

**Result:** pending

```text
```

### S8 — sudoers drop-ins

1. Put the S1 job back (it is what S2 starts):

   ```sh
   sudo ./install-daemon.sh bntest bntest -- \
     /Applications/BNSpike.app/Contents/MacOS/bnspike probe /Users/bntest/Documents \
     -- -a /Users/bntest/Documents /Users/Shared/bnspike/out-bntest/
   ```

2. Install the locked control key with the stand-in dispatcher:
   `sudo ./setup-control.sh "$ADMIN" ~/bnspike_control.pub`
3. Check that the rule applies, and that nothing else became passwordless:

   ```sh
   sudo -k
   sudo -n /usr/local/libexec/bnspike-dispatch ctl ping </dev/null   # runs: uid=0
   sudo -n -l | grep bnspike-dispatch
   sudo -n /bin/ls /var/root                                            # must be refused
   ```

**Pass when** the dispatcher runs without a password and `/bin/ls` asks for
one ("a password is required"). If your account already had passwordless sudo
for everything, say so in the result.

**Result:** pending

```text
```

### S2 — Starting the job through the control key

On the source Mac, check again that **"Allow full disk access for remote
users" is OFF**. Then, **from the Mac mini**:

```sh
ssh -i ~/.ssh/bnspike_control -o IdentitiesOnly=yes "$ADMIN@$TESTMAC" 'ctl start bntest'
```

Expect `kickstart exit=0`. Then on the source Mac:
`sleep 5; tail -8 /Users/Shared/bnspike/bntest.log`

**Pass when** that run shows `fda: granted`, `read …: ok` and `rsync exit: 0`.

**Result:** pending

```text
```

### S12 (macOS) — the locked control key

From the **Mac mini**. `C` holds the options used for every command:

```sh
C="-i $HOME/.ssh/bnspike_control -o IdentitiesOnly=yes"
H="$ADMIN@$TESTMAC"
ssh $C $H 'ctl ping'                                  # 1
ssh $C $H "ctl log bntest 'my module' \"x y\""        # 2
printf '{"job":1}' | ssh $C $H 'ctl submit bntest'    # 3
ssh $C $H 'ctl ping; id'                              # 4
ssh $C $H                                             # 5  (no command)
scp $C /etc/hosts $H:/tmp/bnspike-scp; echo "scp exit=$?"     # 6
ssh $C -W localhost:22 $H; echo "forward exit=$?"             # 7
```

| # | Pass when |
| --- | --- |
| 1 | `uid=0`, `arg3=[ctl ping]` |
| 2 | `arg3=[ctl log bntest 'my module' "x y"]`, quotes and spaces intact |
| 3 | `stdin_bytes=9` |
| 4 | `arg3=[ctl ping; id]` and only one `uid=` line: `; id` was not run separately |
| 5 | The dispatcher prints `arg3=[]` and the connection closes; no shell prompt |
| 6 | `scp` fails, and `/tmp/bnspike-scp` does not exist on the source Mac |
| 7 | Refused ("administratively prohibited") with a non-zero exit |

**Result:** pending

```text
```

### S5 — Installing an unsigned package over SSH

1. On the source Mac: `./make-app.sh --pkg ~/bnspike.pkg`, then copy it to the
   Mac mini: `scp ~/bnspike.pkg "$OPERATOR@$SERVER:"`
2. From the **Mac mini**, with your ordinary login (your own key or password,
   **not** the control key):

   ```sh
   ssh -t "$ADMIN@$TESTMAC" 'sudo rm -rf /Applications/BNSpike.app /Users/Shared/bnspike.pkg'
   scp ~/bnspike.pkg "$ADMIN@$TESTMAC:/Users/Shared/"
   ssh -t "$ADMIN@$TESTMAC" 'sudo installer -pkg /Users/Shared/bnspike.pkg -target /'
   ssh "$ADMIN@$TESTMAC" 'xattr -l /Users/Shared/bnspike.pkg; ls -d /Applications/BNSpike.app'
   ```

**Pass when** the installer prints "The install was successful.", the package
has no `com.apple.quarantine` attribute, and the app is in `/Applications`.

**Result:** pending

```text
```

## B. The Mac mini

### B.0 Set up the push key and rrsync

1. On the **source Mac**: `./push-test.sh setup`, then copy the key:
   `scp ~/.ssh/bnspike_push.pub "$OPERATOR@$SERVER:"`
2. On the **Mac mini**, as yourself (no sudo): `./setup-rrsync.sh ~/bnspike_push.pub`

### S3 — rrsync accepts the agent's options

"Allow full disk access for remote users" must be **ON** on the Mac mini. On
the **source Mac**: `./push-test.sh all`. Then on the **Mac mini**:

```sh
cd "$BACKUP_VOL/bnspike-staging/testhost/$TESTUSER/mod/Photos/2019"
ls -li
xattr -l DSC_0002.NEF
```

**Pass when** steps 1–5 end with `exit=0`, step 4 shows `*deleting`, step 6
is refused with an rrsync error, `ls -li` shows the same inode number for
`DSC_0001.NEF` and `DSC_0001-hardlink.NEF`, and `xattr -l DSC_0002.NEF` shows
`rsync.%stat` starting with `100640` (the original permissions) and
`com.bleiben.tag` on `DSC_0001.NEF`.

**Result:** pending

```text
```

### S14 — The verify pass finds silent changes

On the **source Mac**: `./push-test.sh s14`, then run the `cat` command it
prints, on the Mac mini.

**Pass when** the plain dry run lists nothing for `Photos/s14.bin`, the
verify pass prints a line starting with `>fc` and with `.` in the 4th and 5th
characters for it, and the file on the Mac mini still contains `AAAAAAAA`.

**Result:** pending

```text
```

### S13 — When the Mac mini refuses the write

1. On the Mac mini: System Settings → General → Sharing → Remote Login → ⓘ →
   turn **"Allow full disk access for remote users" OFF**.
2. On the source Mac: `./push-test.sh all`. Only step 1 matters.
3. Turn the setting back **ON**.

**Pass when** the error lines of step 1 include `[receiver]` or `[generator]`
next to "Operation not permitted".

Possible failure: `rrsync` itself changes into the staging folder before rsync
starts, so the error may instead read `rrsync error: unable to chdir to
restricted dir: [Errno 1] Operation not permitted`, with no tag. That is a
FAIL for this spike: paste it exactly, because the agent's error classifier
then needs one more rule.

**Result:** pending

```text
```

### S6 — Cloning a folder tree on the backup drive

```sh
python3 clone_test.py "$BACKUP_VOL/bnspike-staging/testhost/$TESTUSER/mod" \
                      "$BACKUP_VOL/bnspike-staging/clone-test"
```

If macOS asks whether Terminal may access a removable volume, allow it and
note that it asked.

**Pass when** it ends with `S6: PASS`.

**Result:** pending

```text
```

### S7 — Signal Note to Self

```sh
signal-cli link -n "bn-backup Mac mini" | tee >(head -1 | qrencode -t ansiutf8)
```

On your phone: Signal → Settings → Linked devices → **+**, and scan the code.
Then, with your number in place of the example:

```sh
signal-cli -a +61400000000 receive
signal-cli -a +61400000000 send --note-to-self -m "bn-backup spike S7"
```

**Pass when** the message appears in your **Note to Self** chat on the phone.
Keep this link: the real server will use it.

**Result:** pending

```text
```

### S10 and S11 — The backup drive, with nobody logged in

1. Install the Python the server will use and note its path:

   ```sh
   uv python install 3.12
   PY=$(uv python find 3.12); echo "$PY"
   ```

2. **S10a, from Terminal:** `"$PY" volume_test.py "$BACKUP_VOL"`. Note any
   consent prompt.
3. **S10b, from a LaunchDaemon:** copy the script where the job can read it and
   install a job that runs at every boot:

   ```sh
   sudo mkdir -p /Users/Shared/bnspike && sudo chmod 1777 /Users/Shared/bnspike
   cp volume_test.py /Users/Shared/bnspike/
   sudo ./install-daemon.sh s10 "$OPERATOR" --run-at-load -- \
     "$PY" /Users/Shared/bnspike/volume_test.py "$BACKUP_VOL" 180
   ```

   It runs once immediately (you are logged in). Then restart **without
   logging in afterwards**:
   - FileVault on: `sudo fdesetup authrestart` (unlocks the disk for this one
     restart, then stops at the login window).
   - FileVault off: a normal restart, with automatic login turned off.

   Wait 4 minutes. Without logging in at the Mac mini, read the result from
   another computer:
   `ssh "$OPERATOR@$SERVER" cat /Users/Shared/bnspike/volume_test.log`
4. **S11:** if the run after the restart says `mounted: False`, run
   `sudo defaults write /Library/Preferences/SystemConfiguration/autodiskmount AutomountDisksWithoutUserLogin -bool true`
   and repeat the restart and the check.
5. Remove the job: `sudo launchctl bootout system/ar.bleiben.bnspike.s10`
   and `sudo rm /Library/LaunchDaemons/ar.bleiben.bnspike.s10.plist`

**Pass when** S10a passes, and the run after the restart shows
`logged in at the screen: root`, `mounted: True` and `RESULT: PASS`. Record
whether S11 needed the `autodiskmount` setting, and whether the drive is
encrypted.

**Result:** pending

```text
(S10a output, then the log after each restart)
```

## C. The Debian host

### S12 (Linux) — the locked control key

On the Debian host: `cd ~/bnspike-kit && sudo ./setup-control.sh "$ADMIN" ~/bnspike_control.pub`

Then from the **Mac mini**, run commands 1–7 of S12 (macOS) with
`H="$ADMIN@$LINUXHOST"`. The pass conditions are the same.

**Result:** pending

```text
```

## Cleanup

**Source Mac:**

```sh
sudo launchctl bootout system/ar.bleiben.bnspike.bntest
sudo rm -f /Library/LaunchDaemons/ar.bleiben.bnspike.*.plist
sudo ./setup-control.sh --remove "$ADMIN"
sudo rm -rf /Applications/BNSpike.app /Users/Shared/bnspike /Users/Shared/bnspike.pkg
sudo pkgutil --forget ar.bleiben.bnspike
sudo sysadminctl -deleteUser bntest
rm -rf ~/bnspike-build ~/bnspike.pkg ~/bnspike_control.pub ~/.ssh/bnspike_push ~/.ssh/bnspike_push.pub
```

Then remove BNSpike from Full Disk Access (select it, click **−**), and delete
`~/bnspike-kit`.

**Mac mini:**

```sh
./setup-rrsync.sh --remove
rm -rf ~/bnspike "$BACKUP_VOL/bnspike-staging" ~/bnspike.pkg ~/bnspike_push.pub
rm -f ~/.ssh/bnspike_control ~/.ssh/bnspike_control.pub
sudo rm -rf /Users/Shared/bnspike
```

Keep the Signal link and, if S11 needed it, the `autodiskmount` setting. Then
delete `~/bnspike-kit`.

**Debian host:** `sudo ./setup-control.sh --remove "$ADMIN"`, then delete
`~/bnspike-kit` and `~/bnspike_control.pub`.
