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
