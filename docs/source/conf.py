# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Version — single source of truth is the repo-root VERSION file.
# conf.py must NEVER hard-code a version here; it reads it from ../../
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]  # docs/source/conf.py -> repo root
_VERSION_FILE = _REPO_ROOT / "VERSION"
try:
    version = _VERSION_FILE.read_text(encoding="utf-8").strip()
except FileNotFoundError:
    version = "0.0.0"
release = version

# ---------------------------------------------------------------------------
# Import path for autodoc: make the bridge package importable.
#
# Import side effects in claude_code_qq_bridge.bridge are limited to:
#   - load_env()            (reads .env / sets os.environ — harmless)
#   - os.environ.pop(TMUX)  (clears inherited tmux env vars)
#   - constant definitions
# It does NOT open network connections, start QQ, spawn tmux, or create
# processes at import time — everything heavy happens inside cli()/main().
# Verified manually before enabling autodoc. If this ever changes, mock the
# module instead of removing autodoc:
#   autodoc_mock_imports = ["aiohttp", "httpx"]
# ---------------------------------------------------------------------------
sys.path.insert(0, str(_REPO_ROOT / "packages" / "claude-code-qq-bridge" / "src"))

# -- Project information -----------------------------------------------------
project = "agent-keep"
author = "xuyang"
copyright = "2026, xuyang"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# The documentation is written in English.
language = "en"

# autosummary generates one stub page per documented object.
autosummary_generate = True

# -- Autodoc -----------------------------------------------------------------
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

# -- Intersphinx -------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- Options for HTML output -------------------------------------------------
html_theme = "sphinx_rtd_theme"
