#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# One version for everything (CLAUDE.md §3): the tag, server/pyproject.toml,
# bn_backup.__version__ and agent/Cargo.toml must agree.
# Usage: scripts/check-versions.sh VERSION    (for example 2.0.0)
set -eu
V=${1:?usage: check-versions.sh VERSION}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
py=$(sed -n 's/^version = "\(.*\)"$/\1/p' "$ROOT/server/pyproject.toml" | head -1)
init=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/server/src/bn_backup/__init__.py")
cargo=$(sed -n 's/^version = "\(.*\)"$/\1/p' "$ROOT/agent/Cargo.toml" | head -1)
ok=true
for pair in "pyproject.toml:$py" "__init__.py:$init" "Cargo.toml:$cargo"; do
    if [ "${pair#*:}" != "$V" ]; then
        echo "version mismatch: ${pair%%:*} has ${pair#*:}, the tag says $V" >&2
        ok=false
    fi
done
$ok && echo "all versions are $V"
