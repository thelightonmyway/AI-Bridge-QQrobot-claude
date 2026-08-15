# agy-qq-bridge

A QQ bridge that runs Google Antigravity (AGY) in a local `tmux` session and relays private QQ messages to it. AGY output is read from its `transcript.jsonl` logs; input is delivered via `tmux send-keys`.

## Features

- Multi-turn chat between QQ and a persistent AGY session
- Session restart and interrupt commands
- Only responds to `MASTER_OPENID` (auto-binds to the first user when empty)

## Installation

Install from this repository:

```bash
pip install ./packages/agy-qq-bridge
```

## Configuration

Copy `.env.example` to `.env` and fill in the required values:

| Variable       | Description                                                           |
|----------------|-----------------------------------------------------------------------|
| `APP_ID`       | QQ bot AppID (QQ bot platform)                                       |
| `CLIENT_SECRET`| QQ bot client secret                                                 |
| `MASTER_OPENID`| Your QQ OpenID; only this user's messages are answered               |
| `TMUX_SESSION` | tmux session name to run AGY in (default `0`)                        |
| `BRAIN_DIR`    | directory containing AGY `transcript.jsonl` (default `~/.gemini/antigravity-cli/brain`) |
| `AGY_START_CMD`| command used to start AGY inside tmux                                |

## Run

```bash
agy-qq-bridge
```

## Commands

| Command | Effect |
|---------|--------|
| `text` | forward to AGY |
| `/new`, `/reset`, `/清空`, `/新对话` | restart AGY in a new session |
| `/stop`, `/停止`, `/kill` | interrupt AGY |

## License

MIT. See `LICENSE`.

Portions of the original implementation are derived from zz327455573/agent-keep under the MIT License.
