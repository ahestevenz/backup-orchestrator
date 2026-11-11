#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Regenerate the library section of THIRD_PARTY_NOTICES.md (CLAUDE.md §13 item 5).

Reads the runtime dependency trees (Python: `uv export` + `pip-licenses`;
Rust: `cargo license`) and fails when a license is not on the allowed list.

Usage (from the repository root):
    python3 scripts/third_party_notices.py          # rewrite the section
    python3 scripts/third_party_notices.py --check  # fail if it is out of date
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
BEGIN = "<!-- BEGIN generated"
END = "<!-- END generated -->"
ALLOWED = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "Unicode-3.0",
    "Zlib",
    "MPL-2.0",
    "PSF-2.0",
}
# pip-licenses reports trove classifiers or free text; map them to SPDX.
PY_NAMES = {
    "MIT License": "MIT",
    "MIT": "MIT",
    "Apache Software License": "Apache-2.0",
    "Apache-2.0": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "BSD-3-Clause": "BSD-3-Clause",
    "Python Software Foundation License": "PSF-2.0",
    "PSF-2.0": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "ISC License (ISCL)": "ISC",
}


def run(argv: list[str], cwd: Path) -> str:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=True).stdout


def allowed(expr: str) -> bool:
    """SPDX expression: any OR-alternative where every AND-part is allowed."""
    expr = expr.replace("(", "").replace(")", "").replace("/", " OR ")
    return any(
        all(part.strip() in ALLOWED for part in alt.split(" AND "))
        for alt in re.split(r"\s+OR\s+", expr)
    )


def norm(name: str) -> str:
    """PEP 503 name normalisation (pydantic_core == pydantic-core)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def python_deps() -> list[tuple[str, str]]:
    server = ROOT / "server"
    reqs = run(["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "--format", "requirements-txt"], server)
    # The server runs on macOS and Linux only: skip Windows-only requirements.
    names = sorted(
        {
            norm(re.split(r"[=<>;\s]", ln)[0])
            for ln in reqs.splitlines()
            if ln and ln[0].isalpha() and "win32" not in ln
        }
    )
    data = json.loads(run(["uv", "run", "--with", "pip-licenses", "pip-licenses", "--format=json", "--from=mixed"], server))
    by = {norm(d["Name"]): d["License"] for d in data}
    out = []
    for n in names:
        lic = by.get(n, "UNKNOWN")
        spdx = " OR ".join(PY_NAMES.get(x.strip(), x.strip()) for x in lic.split(";"))
        out.append((n, spdx))
    return out


def rust_deps() -> list[tuple[str, str]]:
    data = json.loads(run(["cargo", "license", "--json", "--avoid-dev-deps", "--avoid-build-deps"], ROOT / "agent"))
    return sorted((d["name"], d.get("license") or "UNKNOWN") for d in data if d["name"] != "bn-backup-agent")


def table(title: str, col: str, rows: list[tuple[str, str]]) -> str:
    lines = [f"### {title}", "", f"| {col} | License |", "| --- | --- |"]
    lines += [f"| {n} | {lic} |" for n, lic in rows]
    return "\n".join(lines) + "\n"


def main() -> int:
    py, rs = python_deps(), rust_deps()
    bad = [f"{n}: {lic}" for n, lic in py + rs if not allowed(lic)]
    section = (
        f"{BEGIN}: do not edit by hand. CI regenerates this section from\n"
        "     the dependency trees (scripts/third_party_notices.py). -->\n\n"
        + table("Server (Python)", "Package", py)
        + "\n"
        + table("Agent (Rust)", "Crate", rs)
        + "\n"
        + END
    )
    text = NOTICES.read_text(encoding="utf-8")
    start, end = text.index(BEGIN), text.index(END) + len(END)
    new = text[:start] + section + text[end:]
    if bad:
        print("licenses not on the allowed list (ask the owner first):", *bad, sep="\n  ")
        return 1
    if "--check" in sys.argv:
        if new != text:
            print("THIRD_PARTY_NOTICES.md is out of date; run scripts/third_party_notices.py")
            return 1
        print("THIRD_PARTY_NOTICES.md is up to date")
        return 0
    NOTICES.write_text(new, encoding="utf-8")
    print(f"updated {NOTICES.relative_to(ROOT)}: {len(py)} Python, {len(rs)} Rust dependencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
