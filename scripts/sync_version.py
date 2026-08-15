#!/usr/bin/env python3
"""Sync the root VERSION file into every pyproject.toml [project] version.

The repo-root VERSION is the single manually-maintained version. This script
is the only writer of the derived version fields in the root and the three
internal package pyprojects, so nobody has to hand-edit them.

Usage:
    python3 scripts/sync_version.py

Run it after editing VERSION, then verify with scripts/check_version.py.
Idempotent: no changes are made when versions already match.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "VERSION"
PYPROJECTS = [REPO_ROOT / "pyproject.toml"] + sorted(
    (REPO_ROOT / "packages").glob("*/pyproject.toml")
)

_HEADER_RE = re.compile(r"(?m)^\[([^\]]+)\]\s*$")
_VERSION_RE = re.compile(r'(^version\s*=\s*)"[^"]*"', re.M)


def project_version(text: str) -> str | None:
    """Return the version string under the [project] table, or None."""
    sections = _split_sections(text)
    for header, body in sections:
        if header == "project":
            m = _VERSION_RE.search(body)
            return m.group(1) if m else None
    return None


def set_project_version(text: str, version: str) -> tuple[str, bool]:
    """Return (new_text, changed) with only the [project] version updated."""
    sections = _split_sections(text)
    changed = False
    for i, (header, body) in enumerate(sections):
        if header == "project":
            new_body = _VERSION_RE.sub(rf'\1"{version}"', body, count=1)
            if new_body != body:
                changed = True
            sections[i] = (header, new_body)
    return "".join(body for _, body in sections), changed


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split TOML into [(header, body_with_header)] preserving order."""
    matches = list(_HEADER_RE.finditer(text))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group(1), text[m.start():end]))
    return out


def main() -> int:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version:
        print(f"❌ VERSION file is empty: {VERSION_FILE}", file=sys.stderr)
        return 1
    if not re.match(r"^\d+\.\d+\.\d+", version):
        print(f"❌ VERSION '{version}' is not a plain semver.", file=sys.stderr)
        return 1

    changed_any = False
    for pf in PYPROJECTS:
        if not pf.exists():
            print(f"❌ missing {pf}", file=sys.stderr)
            return 1
        text = pf.read_text(encoding="utf-8")
        new_text, changed = set_project_version(text, version)
        if changed:
            pf.write_text(new_text, encoding="utf-8")
            changed_any = True
        rel = pf.relative_to(REPO_ROOT)
        print(f"  {str(rel):52s} -> {version}{'   (updated)' if changed else ''}")

    if changed_any:
        print("\nSynced. Run `python3 scripts/check_version.py` to verify.")
    else:
        print("\nAll pyproject.toml already at", version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
