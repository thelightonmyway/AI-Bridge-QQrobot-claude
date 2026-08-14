# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

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

# -- Project information -----------------------------------------------------
project = "AI-Bridge-QQrobot-claude"
author = "xuyang"
copyright = "2026, xuyang"

# -- General configuration ---------------------------------------------------
extensions = [
    "myst_parser",
]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "generated"]

# The documentation is written in English.
language = "en"

# -- Options for HTML output -------------------------------------------------
html_theme = "sphinx_rtd_theme"
