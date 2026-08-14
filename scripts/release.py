#!/usr/bin/env python3
"""AI-Bridge-QQrobot-claude release tool — single source of truth for versioning.

Usage:
    python3 scripts/release.py patch    # 0.1.0 -> 0.1.1
    python3 scripts/release.py minor    # 0.1.1 -> 0.2.0
    python3 scripts/release.py major    # 0.2.0 -> 1.0.0

Behavior:
    1. Verify the git working tree is clean (abort otherwise).
    2. Read the previous git tag and the commits since it.
    3. Bump VERSION (repo-root VERSION file).
    4. Promote [Unreleased] entries in CHANGELOG.md to the new version
       (or auto-draft from git log when empty).
    5. Run tests if pytest + a tests/ dir exist.
    6. Build the Sphinx docs to confirm no errors.
    7. git commit (VERSION + CHANGELOG + docs changes).
    8. Create an annotated git tag (vX.Y.Z).

    NEVER pushes. After tagging it prints what to do next.

Set BRIDGE_DOCS_NO_BUILD=1 to skip the Sphinx build (debugging only).
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "VERSION"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"
DOCS_SOURCE = REPO_ROOT / "docs" / "source"
DOCS_BUILD = REPO_ROOT / "docs" / "_build" / "html"

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, **kw)


def sh(cmd):
    p = run(cmd)
    if p.returncode != 0:
        raise RuntimeError(f"$ {cmd!r} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


def current_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def bump(version: str, part: str) -> str:
    m = SEMVER_RE.match(version)
    if not m:
        raise SystemExit(f"VERSION '{version}' is not a clean semver (drop pre-release suffix).")
    major, minor, patch = (int(g) for g in m.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def git_is_clean() -> bool:
    return not run(["git", "status", "--porcelain"]).stdout.strip()


def last_tag() -> str:
    p = run(["git", "describe", "--tags", "--abbrev=0"])
    if p.returncode == 0:
        return p.stdout.strip()
    return ""  # no tags yet


def commits_since(tag: str) -> list[str]:
    spec = f"{tag}..HEAD" if tag else "HEAD"
    p = run(["git", "log", "--oneline", "--no-decorate", spec])
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def extract_unreleased() -> str:
    text = CHANGELOG_FILE.read_text(encoding="utf-8")
    m = re.search(r"^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        return ""
    return m.group(1).strip()


def draft_changelog(tag: str) -> str:
    """Best-effort auto-draft when [Unreleased] is empty; AI 会据此润色。"""
    commits = commits_since(tag)
    added, fixed, changed = [], [], []
    for c in commits:
        msg = c.split(":", 1)[-1].strip()
        low = msg.lower()
        if low.startswith(("fix", "fix(", "bug", "修复")):
            fixed.append(msg)
        elif low.startswith(("feat", "add", "new", "新增")):
            added.append(msg)
        else:
            changed.append(msg)
    lines = []
    if added:
        lines.append("### Added")
        lines += [f"- {m}" for m in added[:20]]
    if changed:
        lines.append("### Changed")
        lines += [f"- {m}" for m in changed[:20]]
    if fixed:
        lines.append("### Fixed")
        lines += [f"- {m}" for m in fixed[:20]]
    if not lines:
        lines.append("- 本次发布包含若干未分类改动。")
    return "\n".join(lines)


def promote_changelog(new_ver: str, unreleased: str) -> None:
    text = CHANGELOG_FILE.read_text(encoding="utf-8")
    header = f"## [{new_ver}] - {datetime.date.today().isoformat()}"
    # Remove the old [Unreleased] marker line(s); keep body.
    m = re.search(r"^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    body = (m.group(1).strip() if m and m.group(1).strip() else unreleased)
    if not body:
        raise SystemExit("CHANGELOG [Unreleased] is empty and no fallback body provided.")
    new_section = f"{header}\n\n{body}\n"
    # Replace "## [Unreleased]" with the new versioned section, then prepend a fresh Unreleased.
    replaced = text[: m.start()] + new_section + text[m.end():]
    fresh = text[: m.start()] + "## [Unreleased]\n\n" + replaced[m.start():]
    CHANGELOG_FILE.write_text(fresh, encoding="utf-8")


def run_tests() -> bool:
    tests = REPO_ROOT / "tests"
    has_pytest = run(["python3", "-c", "import pytest"]).returncode == 0
    if not (tests.is_dir() and has_pytest):
        print("  - No tests/ dir or pytest — skipping test step.")
        return True
    p = run(["python3", "-m", "pytest", "-q"])
    if p.returncode != 0:
        print(p.stdout)
        print(p.stderr)
        return False
    print("  - Tests passed.")
    return True


def build_docs() -> bool:
    if os.environ.get("BRIDGE_DOCS_NO_BUILD"):
        print("  - BRIDGE_DOCS_NO_BUILD set — skipping docs build.")
        return True
    p = run(["python3", "-m", "sphinx", "-b", "html", str(DOCS_SOURCE), str(DOCS_BUILD)])
    if p.returncode != 0:
        print(p.stdout[-2000:])
        print(p.stderr[-2000:])
        return False
    print("  - Sphinx build OK (no errors).")
    return True


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("patch", "minor", "major"):
        print(__doc__)
        return 2
    part = sys.argv[1]

    if not git_is_clean():
        print("❌ Working tree has uncommitted changes. Commit or stash first.")
        print(run(["git", "status", "--short"]).stdout)
        return 1

    old_ver = current_version()
    tag = last_tag()
    commits = commits_since(tag)
    print(f"  current VERSION: {old_ver}")
    print(f"  previous tag:    {tag or '(none)'}")
    print(f"  commits since:   {len(commits)}")
    for c in commits[:10]:
        print(f"    {c}")

    new_ver = bump(old_ver, part)
    print(f"  bumping {part}: {old_ver} -> {new_ver}")

    # 1) promote unreleased
    unreleased = extract_unreleased()
    if not unreleased:
        print("  [Unreleased] empty — auto-drafting from git log.")
        unreleased = draft_changelog(tag)
    promote_changelog(new_ver, unreleased)

    # 2) write VERSION
    VERSION_FILE.write_text(new_ver + "\n", encoding="utf-8")

    # 3) tests
    if not run_tests():
        print("❌ Tests failed — not creating a release. CHANGELOG/VERSION were left modified.")
        return 1

    # 4) docs
    if not build_docs():
        print("❌ Docs build failed — not creating a release.")
        return 1

    # 5) commit + tag
    files = [str(VERSION_FILE.relative_to(REPO_ROOT)),
             str(CHANGELOG_FILE.relative_to(REPO_ROOT))]
    p = run(["git", "add", *files])
    # docs/_build is gitignored; nothing else is expected to change
    if run(["git", "status", "--porcelain"]).stdout.strip():
        run(["git", "add", "-A"])
    msg = f"Release {new_ver}\n\n{commits[0] if commits else ''}"
    sh(["git", "commit", "-q", "-m", msg])
    tag_name = f"v{new_ver}"
    sh(["git", "tag", "-a", tag_name, "-m", f"Release {new_ver}"])

    print()
    print(f"✅ Release {tag_name} created locally (commit + tag).")
    print()
    print(f"  version : {old_ver} -> {new_ver}")
    print(f"  tag     : {tag_name}")
    print(f"  branch  : {sh(['git', 'branch', '--show-current'])}")
    print()
    print("  Release ready. Push to remote?  (not done automatically)")
    print(f"    git push origin {sh(['git', 'branch', '--show-current'])}")
    print(f"    git push origin {tag_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
