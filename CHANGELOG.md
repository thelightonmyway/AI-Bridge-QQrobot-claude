# Changelog

This file is maintained by `scripts/release.py`: on every release, the entries
under `[Unreleased]` are moved to a versioned section and a new version is
created.

Format conventions:

- One `## [x.y.z] - YYYY-MM-DD` section per version;
- Each section uses `### Added / Changed / Fixed / Removed` categories;
- `## [Unreleased]` always sits at the top and records unpublished changes.

## [Unreleased]

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
