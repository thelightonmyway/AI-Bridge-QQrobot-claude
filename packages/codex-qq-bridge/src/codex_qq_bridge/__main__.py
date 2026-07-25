#!/usr/bin/env python3
"""CLI entry: python -m codex_qq_bridge"""
import sys
from .bridge import cli

if __name__ == "__main__":
    sys.exit(cli())
