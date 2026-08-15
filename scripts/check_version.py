#!/usr/bin/env python3
"""Verify every version-bearing location matches the repo-root VERSION file.

The root VERSION is the single manually-maintained version. Everything else
must follow it automatically:
  1. root + internal package pyproject.toml [project].version
  2. Sphinx docs/source/conf.py (must read VERSION, not hard-code)
  3. installed distributions' runtime version (importlib.metadata.version)

Usage:
    python3 scripts/check_version.py

If a pyproject drifted, run `python3 scripts/sync_version.py` first.
Exit code 0 = everything consistent, 1 = at least one mismatch.
"""
from __future__ import annotations

import importlib.metadata
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "VERSION"
PYPROJECTS = [REPO_ROOT / "pyproject.toml"] + sorted(
    (REPO_ROOT / "packages").glob("*/pyproject.toml")
)
CONF_PY = REPO_ROOT / "docs" / "source" / "conf.py"
RUNTIME_DISTS = [
    ("claude-code-qq-bridge", "claude"),
    ("codex-qq-bridge", "codex"),
    ("agy-qq-bridge", "agy"),
]

_HEADER_RE = re.compile(r"(?m)^\[([^\]]+)\]\s*$")
_VERSION_RE = re.compile(r'(^version\s*=\s*)"([^"]*)"', re.M)
_HARDCODED_VERSION_RE = re.compile(r'(?m)^\s*version\s*=\s*"(\d+\.\d+\.\d+)"')

# The one hard-coded literal allowed in conf.py: sentinel when VERSION is absent.
_ALLOWED_CONF_FALLBACK = "0.0.0"

_failures: list[str] = []
_passes: list[str] = []


def _ok(what: str, detail: str) -> None:
    _passes.append(f"  ✅ {what}: {detail}")


def _fail(what: str, detail: str) -> None:
    _failures.append(f"  ❌ {what}: {detail}")


def project_version(text: str) -> str | None:
    for header, body in _split_sections(text):
        if header == "project":
            m = _VERSION_RE.search(body)
            return m.group(2) if m else None
    return None


def _split_sections(text: str) -> list[tuple[str, str]]:
    matches = list(_HEADER_RE.finditer(text))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group(1), text[m.start():end]))
    return out


def check_root_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version:
        _fail("root VERSION", f"file {VERSION_FILE} is empty")
        raise SystemExit(1)
    if not re.match(r"^\d+\.\d+\.\d+", version):
        _fail("root VERSION", f"'{version}' is not a plain semver")
        raise SystemExit(1)
    _ok("root VERSION", version)
    return version


def check_pyprojects(expect: str) -> None:
    for pf in PYPROJECTS:
        rel = pf.relative_to(REPO_ROOT)
        got = project_version(pf.read_text(encoding="utf-8"))
        if got is None:
            _fail(str(rel), "no [project].version found")
        elif got == expect:
            _ok(str(rel), got)
        else:
            _fail(str(rel), f"{got} != root {expect}  (run scripts/sync_version.py)")


def check_sphinx_conf() -> None:
    if not CONF_PY.exists():
        _fail("docs/source/conf.py", "file missing")
        return
    text = CONF_PY.read_text(encoding="utf-8")
    if "VERSION" not in text:
        _fail("docs/source/conf.py", "does not read the root VERSION file")
        return
    for m in _HARDCODED_VERSION_RE.finditer(text):
        if m.group(1) != _ALLOWED_CONF_FALLBACK:
            _fail("docs/source/conf.py", f"hard-codes version '{m.group(1)}'")
            return
    _ok("docs/source/conf.py", "reads root VERSION, no hard-coded version")


def check_runtime(expect: str) -> None:
    for dist_name, label in RUNTIME_DISTS:
        try:
            got = importlib.metadata.version(dist_name)
        except importlib.metadata.PackageNotFoundError:
            _ok(f"runtime {label} ({dist_name})", "not installed — skipped")
            continue
        if got == expect:
            _ok(f"runtime {label} ({dist_name})", got)
        else:
            _fail(f"runtime {label} ({dist_name})", f"{got} != root {expect}  (reinstall the package)")


def main() -> int:
    expect = check_root_version()
    check_pyprojects(expect)
    check_sphinx_conf()
    check_runtime(expect)

    print("version consistency check (single source: root VERSION):")
    for line in _passes:
        print(line)
    for line in _failures:
        print(line)

    if _failures:
        print("\n❌ " + f"{len(_failures)} mismatch(es). Fix by running scripts/sync_version.py"
                        " and reinstalling affected packages, then re-check.")
        return 1
    print("\n✅ all version-bearing locations match root VERSION", expect)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
