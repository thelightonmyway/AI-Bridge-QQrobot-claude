# claude-code-qq-bridge

A QQ bridge that runs Claude Code in a local `tmux` session and relays private QQ messages to it. Replies are read from Claude Code's structured JSONL logs (clean text, no terminal control characters); input is delivered via `tmux send-keys`. Permission prompts are surfaced as QQ inline approval buttons.

## Features

- Multi-turn chat between QQ and a persistent Claude Code session
- QQ approval buttons for permission prompts (allow once / always allow / deny)
- `/resume` lists recent sessions; `/resume N` restores one
- `/btw <question>` asks Claude Code without terminal escape (zero-Escape)
- `/sendfile <path>` and `/sendimg <path>` send a local file/image to QQ
- `/cd <path>` and `/ls [path]` manage the working directory
- Automatic recovery when the Claude Code process exits
- Only responds to `MASTER_OPENID` (auto-binds to the first user when empty)

## Installation

Install from this repository:

```bash
pip install ./packages/claude-code-qq-bridge
```

## Configuration

Copy `.env.example` to `.env` and fill in the required values:

| Variable       | Description                                              |
|----------------|----------------------------------------------------------|
| `APP_ID`       | QQ bot AppID (QQ bot platform)                          |
| `CLIENT_SECRET`| QQ bot client secret                                    |
| `MASTER_OPENID`| Your QQ OpenID; only this user's messages are answered  |
| `TMUX_SESSION` | tmux session number to run Claude Code in (default `1`) |

## Run

```bash
claude-code-qq-bridge
```

## Commands

| Command | Effect |
|---------|--------|
| `text` | forward to Claude Code |
| `/clear`, `/new`, `/reset`, `/qingkong`, `/xin duihua` | start a new session |
| `/stop`, `/tingzhi`, `/kill` | interrupt the current task |
| `/resume` | list recent sessions |
| `/resume N` | restore session N |
| `/cd <path>` | change working directory |
| `/ls [path]` | list files |
| `/btw <question>` | ask without terminal escape |
| `/mode` | toggle permission mode (`/mode status` to query) |
| `/compact` | compact context and report token usage |
| `/sendfile <path>` | send a local file to QQ |
| `/sendimg <path>` | send a local image to QQ |

## License

MIT. See `LICENSE`.

Portions of the original implementation are derived from zz327455573/agent-keep under the MIT License.
