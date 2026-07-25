# Architecture

## Core Concept

Each bridge is a **channel adapter** + **agent adapter** combo. The internal logic (message injection, output capture, session management, lifecycle control) is shared across all bridges.

```
┌─────────────────────────────────────────────────────────────┐
│                        Bridge                                │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │               Channel Adapter                         │    │
│  │  ┌──────────────────┐  ┌──────────────────────────┐  │    │
│  │  │  Input: Receive   │  │  Output: Send reply      │  │    │
│  │  │  messages from IM │  │  back to IM platform     │  │    │
│  │  └──────────────────┘  └──────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────┘    │
│                          │                                    │
│                          ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │               Agent Adapter                           │    │
│  │  ┌──────────────────┐  ┌──────────────────────────┐  │    │
│  │  │  Inject: Send     │  │  Capture: Read agent     │  │    │
│  │  │  message to agent │  │  output (JSONL / stdout) │  │    │
│  │  └──────────────────┘  └──────────────────────────┘  │    │
│  │  ┌──────────────────┐  ┌──────────────────────────┐  │    │
│  │  │  Session: Monitor │  │  Lifecycle: Start/stop/  │  │    │
│  │  │  agent state      │  │  restart agent process   │  │    │
│  │  └──────────────────┘  └──────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Channel Abstraction

A channel adapter is the interface to an IM platform. It handles:

1. **Authentication** — Connecting to the platform's API (WebSocket, HTTP, etc.)
2. **Message receiving** — Parsing incoming messages into a standardized format
3. **Message sending** — Sending text, cards, buttons, media back to the user

### Standardized Message Format

```python
# Input (from IM to bridge)
{
    "user_id": "xxx",           # Platform user ID
    "channel": "qq",            # Platform identifier
    "message": "帮我检查服务器",  # Raw message text
    "message_id": "xxx",        # For reply threading
    "timestamp": 1234567890
}

# Output (from bridge to IM)
{
    "user_id": "xxx",
    "channel": "qq",
    "reply": "检查完成",         # Text reply
    "buttons": [],              # Optional card/button payload
    "media": []                 # Optional file/image attachments
}
```

### Current Channel: QQ

The QQ channel adapter uses the **Tencent QQ Bot WebSocket Gateway** (official API). It's a full-duplex WebSocket connection that:
- Receives C2C (private) messages in real-time
- Sends text, markdown, and button card messages
- Supports file/image attachments via media upload API

QQ was chosen as the reference implementation because:
- Chinese users (the primary early adopters) are on QQ
- The QQ Bot API is mature and well-documented
- WebSocket provides real-time bidirectional communication

### Adding a New Channel

To add a new channel (e.g., Telegram), you need to:

1. Create a new adapter that implements the channel interface
2. Handle authentication for the target platform
3. Map incoming messages to the standardized format
4. Map outgoing messages to the platform's API

The agent runtime, output capture, and session management stay the same.

## Agent Adapter

An agent adapter handles the interaction with a specific CLI agent. It manages:

### 1. Process Management

**tmux (Linux):** Agent runs in a persistent tmux session. The bridge sends keys via `tmux send-keys` and captures output by reading agent log files.

**ConPTY (Windows):** Agent runs in a Windows Pseudo Console (ConPTY). The bridge spawns the agent process directly and reads its stdout/stderr.

### 2. Output Capture

Two strategies are used:

**JSONL Log Reading (primary):** Most CLI agents (Claude Code, Codex, AGY) write structured logs in JSONL format. The bridge reads these incrementally, extracting only the `assistant` role messages. This avoids ANSI control characters and terminal noise.

**stdout Capture (fallback):** For agents that don't write JSONL logs, the bridge reads stdout directly from the PTY/ConPTY, stripping control characters.

### 3. Session Management

- **Start:** Bridge starts the agent (or ensures it's running in tmux)
- **Monitor:** Bridge checks agent health periodically (process alive, session file exists)
- **Restart:** On crash, bridge auto-restarts the agent
- **Reset:** `/new` command kills the current session, starts a fresh one

### 4. State Detection

Some agents (Claude Code) have approval flows. The bridge detects these by monitoring the agent's session state file for `waitingFor` fields, then presents approval buttons to the user via the IM channel.

## Data Flow

### Normal Message Flow

```
1. User sends message via QQ: "清一下服务器日志"
2. QQ Channel Adapter receives message
3. Bridge sends Escape + message to tmux session
4. Agent processes the request (may take seconds to minutes)
5. Agent writes output to JSONL log file
6. Bridge's background poller reads new JSONL lines
7. Bridge sends clean text back to user via QQ
```

### Approval Flow (Claude Code only)

```
1. Agent needs permission to run a command
2. Agent writes `waitingFor: "permission prompt"` to session file
3. Bridge detects state change → sends QQ card with buttons
4. User clicks "Allow Once" or "Always Allow" or "Deny"
5. Bridge sends corresponding key (1/2/3) to tmux session
6. Agent proceeds with the command
```

### Session Reset Flow

```
1. User sends "/new" via QQ
2. Bridge sends Ctrl+C + "new" command to agent
3. Agent starts new session, writes new JSONL file
4. Bridge detects new file, re-binds the poller to new file
5. Bridge sends "Session reset" confirmation to user
```

## Why This Architecture Works

1. **Decoupled** — Channel and agent adapters are independent. Changing one doesn't affect the other.
2. **Extensible** — New channels and agents can be added without touching existing code.
3. **Proven** — This architecture has been running in production for months across 4 bridges.
4. **Simple** — No complex state machines. No message queues. Just tmux + JSONL + WebSocket.