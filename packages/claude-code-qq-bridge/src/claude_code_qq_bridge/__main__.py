#!/usr/bin/env python3
"""CLI entry: python -m claude_code_qq_bridge"""
import sys
from .bridge import cli

if __name__ == "__main__":
    sys.exit(cli())
