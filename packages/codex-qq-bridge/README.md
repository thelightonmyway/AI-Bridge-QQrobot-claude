# codex-qq-bridge

A QQ bridge that runs the Codex CLI in a local `tmux` session and relays private QQ messages to it. Codex output is read from its `rollout-*.jsonl` logs; input is delivered via `tmux send-keys`.

## Features

- Multi-turn chat between QQ and a persistent Codex session
- Session restart and interrupt commands
- Only responds to `MASTER_OPENID` (auto-binds to the first user when empty)

## Installation

Install from this repository:

```bash
pip install ./packages/codex-qq-bridge
```

## Configuration

Copy `.env.example` to `.env` and fill in the required values:

| Variable       | Description                                               |
|----------------|-----------------------------------------------------------|
| `APP_ID`       | QQ bot AppID (QQ bot platform)                           |
| `CLIENT_SECRET`| QQ bot client secret                                     |
| `MASTER_OPENID`| Your QQ OpenID; only this user's messages are answered   |
| `TMUX_SESSION` | tmux session name to run Codex in (default `codex`)      |
| `CODEX_HOME`   | Codex data directory with `sessions/` (default `~/.codex`) |

## Run

```bash
codex-qq-bridge
```

## Commands

| Command | Effect |
|---------|--------|
| `text` | forward to Codex |
| `/new`, `/reset`, `/qingkong`, `/xin duihua` | restart Codex in a new session |
| `/stop`, `/tingzhi`, `/kill` | interrupt Codex |

## License

MIT. See `LICENSE`.

Portions of the original implementation are derived from zz327455573/agent-keep under the MIT License.
