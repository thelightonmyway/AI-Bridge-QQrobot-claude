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
| `/pwd` | Show the current working directory |
| `/ls [path]` | List directory contents |
| `/context` | Show context usage |
| `/compact` | Compress the current conversation |
| `/clear` | Start a brand-new session |
| `/btw <question>` | Ask a side question without interrupting the main flow |
| `/mode` | Switch permission mode (Auto → Accept edits → Plan → Manual) |
| `/stop` | Interrupt the current task |
| `/sendimg <path>` | Send a local image to Claude |
| `/sendfile <path>` | Send a local file to Claude |

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

## Documentation

Full documentation: <https://agent-keep.readthedocs.io/en/latest/>

## Version

v0.1.0

## License

[MIT](LICENSE)
