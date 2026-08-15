# AGY QQ Bridge for Windows

A Windows-native QQ bridge that runs Google Antigravity (AGY) in a virtual console and relays private QQ messages to it. It connects to the official QQ WebSocket gateway, keeps an `agy.exe` process alive in a Windows pseudo-terminal (ConPTY), reads AGY replies from its `transcript.jsonl` logs, and sends them back to QQ as markdown messages.

## What it is

A standalone single-file script (not installed as a pip package). It starts a persistent AGY session in a hidden ConPTY console, delivers your QQ messages with simulated key input, and streams AGY's model responses to QQ.

## Requirements

- Windows (uses `pywinpty` / ConPTY and `cmd.exe`; there is no tmux)
- Python 3.8+
- The AGY CLI at `AGY_START_CMD` (default `C:\Users\Administrator\AppData\Local\agy\bin\agy.exe`)
- Install dependencies:

```powershell
pip install pywinpty httpx aiohttp
```

## Configuration

Create a `.env` next to the script (it is also looked up in the working directory and home directory) with your QQ bot credentials:

| Variable | Description |
|----------|-------------|
| `APP_ID` | QQ bot AppID (QQ bot platform) |
| `CLIENT_SECRET` | QQ bot client secret |
| `MASTER_OPENID` | Your QQ OpenID; only this user's messages are answered (auto-bound from the first sender when empty) |
| `BRAIN_DIR` | directory containing AGY `transcript.jsonl` (default `%USERPROFILE%\.gemini\antigravity-cli\brain`) |
| `LOG_DIR` | directory for bridge logs (default `%USERPROFILE%\.agy-qq-bridge`) |
| `AGY_START_CMD` | command used to start AGY (default `C:\Users\Administrator\AppData\Local\agy\bin\agy.exe --dangerously-skip-permissions`) |

## Basic usage

```powershell
python agy_qq_bridge_win.py
```

Only one instance may run at a time. Message the bot to start; the first sender is bound as `MASTER_OPENID` if it is not set.

| Command | Effect |
|---------|--------|
| `text` | forward to AGY |
| `/new`, `/reset`, `/清空`, `/新对话` | restart AGY in a fresh session |
| `/stop`, `/停止`, `/kill` | send Ctrl+C to interrupt the current task |

## Limitations

- Windows only; requires `pywinpty` (ConPTY). Linux/macOS use the tmux-based bridge instead.
- Replies are polled from `transcript.jsonl`; only final model responses are forwarded.
- Only the `MASTER_OPENID` user is answered.
- Replies are sent as markdown messages, truncated at 4000 characters.

## License

MIT. See `LICENSE`.

Portions of the original implementation are derived from zz327455573/agent-keep under the MIT License.
