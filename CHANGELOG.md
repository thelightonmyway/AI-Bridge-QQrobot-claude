# Changelog

This file is maintained by `scripts/release.py`: on every release, the entries
under `[Unreleased]` are moved to a versioned section and a new version is
created.

Format conventions:

- One `## [x.y.z] - YYYY-MM-DD` section per version;
- Each section uses `### Added / Changed / Fixed / Removed` categories;
- `## [Unreleased]` always sits at the top and records unpublished changes.

## [Unreleased]

### Added

- Added `scripts/setup-codex.sh` to install or detect CLIProxyAPI, run Codex
  device OAuth, discover the local host and port, configure an explicit
  `proxy-url`, and verify `gpt-5.6-sol`.
- The Codex installer generates a local API key and safely backs up and updates
  both `~/.claude.json` and `~/.claude/settings.json`, removing conflicting old
  DeepSeek/Kimi model selectors while preserving unrelated settings.
- Added `docs/codex.md` and isolated temporary-HOME tests covering setup,
  upstream release installation, OAuth, model verification, and idempotence.

### Changed

- `start.sh` now provides opt-in CLIProxyAPI startup and status checks after a
  successful Codex setup; non-Codex users retain the original behavior.
- Documented the known compatibility limitation where some built-in Claude Code
  subagents, including Explore, may request a Claude model on a Codex-only backend.

### Fixed

- Fixed the README `/mode` command row so the Markdown table renders correctly.

## [0.1.1] - 2026-08-31

### Added

- Long replies are no longer truncated: when a reply is too long for a normal
  QQ message, the complete response is sent as a TXT file.
- Added `/status` to report the local Claude state and visible task progress
  without calling the model or consuming tokens.

### Changed

- `/btw` answers now return the full text (long answers arrive as a TXT file)
  and no longer interrupt the current task while the question is answered.
- `/mode` now queries the current local TUI mode without changing it, while
  `/mode auto|manual|edit|plan` switches directly to the requested mode and
  verifies the result from the Claude TUI.

### Fixed

- Fixed command matching so `/mode` no longer captures `/model`.
## [0.1.0] - 2026-08-14

First stable local release. This release turns the QQ Bridge from "runnable"
into "stable and recoverable":

### Fixed

- Fixed `/resume` leaving `PID=None`, which prevented the session from being bound
- Fixed incorrect PID / session binding
- Fixed normal messages and `/btw` panel content being sent to the Bash process by mistake
- Fixed the abnormal Claude state after `/stop`

### Added

- Automatic `--resume` recovery after Claude exits unexpectedly
- The bridge binds only the Claude inside its own tmux pane (pane-scoped PID detection)
- Re-binding of the new PID after automatic recovery
- Unified logging to `~/agent-keep/logs/bridge.log`
- New `~/agent-keep/start.sh` (start / stop / restart / status)

### Changed

- Logs are now written to `logs/bridge.log` instead of being mixed into `nohup.out`
- Session recovery now detects its own tmux pane to avoid binding another Claude
