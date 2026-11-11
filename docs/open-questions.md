# Open questions

Questions the plan (CLAUDE.md, docs/design.md) did not answer. Under the
end-to-end build agreed on 2026-11-11, the implementation picks a default for
each and lists it here, so the owner can review every choice at the end.

| # | Question | Default chosen | Where |
| --- | --- | --- | --- |
| Q1 | `config migrate` sets `resume_backup: true` when the v1 file has no such key (v2 default), although v1 defaulted to `false`. Keep? | Kept as the plan says, marked `# TODO verify` in the output | `config.py` |
| Q2 | Which account names are valid? The plan only says "required". | Letters, digits, `_`, `.` and `-`, at most 32 characters, not starting with `.` or `-` | `config.py` |
| Q3 | `config migrate -o NEW.yml` when NEW.yml already exists. | Refuse; never overwrite | `cli.py` |
| Q4 | An email `from` address is not listed as required when email is enabled. | Required, together with `smtp_host`, `to` and `password_file` | `config.py` |
| Q5 | The server package's license files are symlinks to the repository root, which a source tarball (sdist) cannot carry. | Release only the wheel, built with `uv build --wheel`; no sdist is published | `server/pyproject.toml`, release workflow |
| Q6 | §5.9 said the verify pass looks for itemize lines starting with `>f`. In a push, rsync marks sent files `<f`, so nothing would ever be reported (found by the agent's end-to-end test). | Accept `<f` and `>f`; CLAUDE.md, the runbook (S14) and `push-test.sh` corrected | `agent/src/rsync.rs` |
| Q7 | §5.10 matched `[receiver]`/`[generator]` exactly, but rsync 3.4 writes `[Receiver]`; and rrsync reports its own refusals (`rrsync error: … Operation not permitted`) without a role tag (likely in spike S13). | Match role tags without case, and treat a denied `rrsync error` line as `server_denied` | `agent/src/classify.rs` |
| Q8 | The `-e` value of §5.9 contains the macOS agent home, which has a space (`/Library/Application Support/…`). rsync splits `-e` on spaces. | Quote paths inside `-e` (rsync honours quotes there) | `agent/src/rsync.rs` |
| Q9 | `ctl start` with no submitted job. | Refused with `no_job` | `agent/src/ctl/start.rs` |
| Q10 | CLAUDE.md §2 lists `agent/packaging/macos/launchd.plist.tmpl`. | Not added: the agent renders the per-user plist itself (`platform/macos.rs`), so there is one source of truth, covered by a test | `agent/src/platform/macos.rs` |
| Q11 | The Linux and macOS integration suites (CLAUDE.md §8) are the acceptance tests of Phases 3, 4 and 6, but need Docker or a CI runner, which this development machine does not have. | Written in Phase 6 and run only in GitHub Actions; until then Phases 3-4 rest on unit tests with fakes plus the agent end-to-end test | `tests/integration/` |
| Q12 | `bn-backup server init` exit code when the final server checks are red. | 2 (like `status`), 0 when green | `server_init.py` |
