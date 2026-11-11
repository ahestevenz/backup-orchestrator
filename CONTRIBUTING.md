# Contributing

Thank you for helping with bleiben Backup Orchestrator. This page explains how
to build and test the project, the rules every change follows, and the
contributor agreement.

## Before your first pull request: the contributor agreement

Every outside contributor signs the [Contributor License Agreement](CLA.md)
once. It lets bleiben keep offering commercial licenses for code that includes
your work (see [`LICENSING.md`](LICENSING.md)); you keep the rights to your own
contributions.

Signing takes one comment: when you open your first pull request, a bot posts
a message asking you to sign. Reply on the pull request with exactly:

    I have read the CLA Document and I hereby sign the CLA

Pull requests are merged only after this check has passed.

## Branches

- `main` holds the released version. Nobody pushes to it directly.
- Version 2 is developed on the `v2` branch, one pull request per phase. Open
  your pull request against `v2` unless a maintainer asks otherwise.

## Building and testing

### Version 1 (`main`)

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install .
pip install pre-commit
pre-commit run --all-files
```

### Version 2 (`v2`)

The server is a Python package in `server/`, the agent a Rust program in
`agent/`. Both are tested on macOS and Linux.

```sh
# server
cd server
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run pytest

# agent
cd agent
cargo fmt --check
cargo clippy -- -D warnings
cargo test
```

## Rules for every change

- **Small, focused commits.** Imperative subject line ("Add host-config
  probe"); the body explains why.
- **Tests are part of done.** A change is finished when its tests pass in CI
  on macOS and Linux.
- **No private data.** Never commit secrets, real phone numbers, email
  addresses or host names. Examples use `example.com`, `+61400000000`,
  `galactica.home.lan`, `athena.home.lan` and `columbia.home.lan`.
- **English** for code, identifiers and comments.
- **Messages for people, not specialists.** Many users are photographers.
  User-facing messages are short and say what failed and what to do next.
- **License headers.** Every new source file starts with these two comment
  lines:

      SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
      Copyright (c) 2018-2026 Ariel Hernandez (bleiben)

- **New dependencies** need a maintainer's approval first, and only licenses
  compatible with the project are accepted (MIT, Apache-2.0, BSD-2-Clause,
  BSD-3-Clause, ISC, Unicode-3.0, Zlib, MPL-2.0, PSF-2.0).

## Questions

Open an issue, or contact bleiben through [www.bleiben.ar](https://www.bleiben.ar).
