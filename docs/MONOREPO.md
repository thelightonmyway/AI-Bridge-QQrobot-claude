# Monorepo Layout

`agent-keep` is now a code-bearing monorepo.

## Packages

- `packages/claude-code-qq-bridge/`
- `packages/codex-qq-bridge/`
- `packages/agy-qq-bridge/`

Each package keeps its own `pyproject.toml`, `src/`, CLI entrypoints, and bridge-specific docs.

## Installation

Install a specific bridge package from this repo:

```bash
pip install ./packages/codex-qq-bridge
pip install ./packages/claude-code-qq-bridge
pip install ./packages/agy-qq-bridge
```

## Why this layout

- The top-level repo is now a real source repository, not docs-only.
- Each bridge can still evolve independently.
- The top-level project preserves the `Agent Keep` umbrella positioning while exposing runnable code.

