# AI-Bridge-QQrobot-claude

> Remote-control your Claude Code agent from QQ on your phone.

**AI-Bridge-QQrobot-claude** is a bridge between **Claude Code** and **QQ**. A Claude Code session
stays alive on your machine 24/7; you talk to it from QQ — start long tasks, check on
them, send files, and approve actions, all from your phone.

The goal: turn your machine into a personal AI workstation you can drive remotely —
one machine, operated from anywhere.

This project is re-developed based on the ideas and base code of
[zz327455573/agent-keep](https://github.com/zz327455573/agent-keep). Many thanks to
the original author for sharing their work.

## Features

- **Always-on agent** — Claude lives in a tmux session and keeps its context; if it
  exits or crashes, the bridge restarts it automatically and restores the session.
- **Approve from QQ** — permission prompts arrive as QQ buttons; tap `allow`,
  `allow always`, or `deny` to respond.
- **Full control from your phone** — change working directories and permission
  modes, send images and files, and manage sessions.

## QQ commands

| Command | Description |
|---|---|
| `/cd <path>` | Change Claude's working directory |
| `/resume` | List recent sessions; `/resume N` restores session N |
| `/resume all` | Rescue-list all top-level Claude sessions across projects |
| `/session-backup` | Copy Claude session JSONL and history to the local backup |
| `/pwd` | Show the current working directory |
| `/ls [path]` | List directory contents |
| `/status` | Show local Claude state plus current and recent visible TUI activity |
| `/context` | Show context usage |
| `/compact` | Compress the current conversation |
| `/clear` | Start a brand-new session |
| `/btw <question>` | Ask a side question without interrupting the main flow |
| `/mode [mode]` | Query current mode or switch to auto/manual/edit/plan |
| `/stop` | Interrupt the current task |
| `/sendimg <path>` | Send a local image from the bridge host to QQ |
| `/sendfile <path>` | Send a local file from the bridge host to QQ |

## What's new in v0.1.4

This is a bug-fix release focused on reliable project switching and session recovery:

- Fixed `/cd` reporting success while Claude was still attached to another
  project's session, and now verify that Claude starts in the requested directory.
- Fixed Bot-created sessions being saved under the wrong Claude project, so they
  remain visible in native Claude `/resume` and `/resume all`.
- Improved `/resume` so it selects the intended Claude session more reliably.
- Added automatic Claude session backups and the local `/session-backup` command
  as an extra recovery safeguard.

## Quick Start

```bash
git clone https://github.com/thelightonmyway/AI-Bridge-QQrobot-claude.git
cd AI-Bridge-QQrobot-claude
./setup.sh <APP_ID> <CLIENT_SECRET>
```

`setup.sh` checks your dependencies, installs the `claude-code-qq-bridge` package,
and writes your QQ bot `APP_ID` and `CLIENT_SECRET` into `~/AI-Bridge-QQrobot-claude/.env`.
Run it with no arguments to get a `.env` template you fill in by hand. Then start the bridge:

```bash
./start.sh start
./start.sh status    # → Bridge running: pid N
```

Send your bot a plain message from QQ — you will get a reply from Claude.

### Optional: Codex / GPT-5.6 Sol

To configure a fresh machine so Claude Code uses Codex OAuth through a local
CLIProxyAPI instance, run:

```bash
./scripts/setup-codex.sh
```

The installer backs up your Claude settings, configures an explicit outbound
proxy, verifies `gpt-5.6-sol`, and enables opt-in CLIProxyAPI startup checks for
the bridge. See [docs/codex.md](docs/codex.md) for details and rollback steps.

## Updating

`setup.sh` also installs a global command `ai-bridge-update` into `~/.local/bin`.
From **any directory**, update the project to the latest version of the `custom`
branch:

```bash
ai-bridge-update
```

Update and then safely restart the QQ bridge (single instance only):

```bash
ai-bridge-update --restart
```

How it works:

* pulls with `git fetch origin custom` + a **fast-forward only** merge — it never
  runs `git reset --hard`, so your own edits are never silently overwritten;
* if any *tracked* file has local modifications, the update stops and lists those
  files instead of overwriting them;
* your `.env` (credentials) is protected — it is checked into `.gitignore` and its
  content is verified unchanged before/after every update;
* the Python editable install of `claude-code-qq-bridge` is refreshed and verified
  (`import claude_code_qq_bridge` + the `claude-code-qq-bridge` CLI).

Alternative (from the project directory):

```bash
cd ~/AI-Bridge-QQrobot-claude
./update.sh            # update only
./update.sh --restart  # update + safe restart
```

## Documentation

Full documentation: <https://ai-bridge-qqrobot-claude.readthedocs.io/en/latest/>

## Version

v0.1.4

## License

[MIT](LICENSE)
