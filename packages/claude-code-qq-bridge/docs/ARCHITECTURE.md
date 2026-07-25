# Claude Code QQ Bridge — Architecture & Case Study

## System Architecture

```
┌─────────────────────┐     ┌─────────────────────────────────┐     ┌──────────────────────────┐
│   QQ Input Layer    │     │        Bridge Layer (Python)     │     │   Claude Code Runtime    │
│                     │     │                                 │     │                          │
│  User sends message │────>│  send_to_claude(): tmux send-keys│────>│  tmux session (claude)  │
│                     │     │                                 │     │                          │
│  Receive reply      │<────│  periodic_poll():               │<────│  JSONL (assistant text) │
│                     │     │    - JSONL (primary)            │     │                          │
│  Approval buttons   │<────│    - session file waitingFor    │<────│  Session file (status)  │
│                     │     │                                 │     │                          │
│  Button click       │────>│  handle_c2c_message():          │────>│  send keystroke (1/2/3) │
└─────────────────────┘     │    parse approve:xxx → tmux     │     └──────────────────────────┘
                            └─────────────────────────────────┘
```

### Data Sources (Read)
- `JSONL` — Claude Code structured brain log (`type=assistant`, text content)
- `session file (.json)` — Session status with `waitingFor` field for approval detection

### Control Path (Write)
- `tmux send-keys` — Injected keystrokes (1=allow, 2=always allow, 3=deny)

---

## Data Flow Detail

### Normal Message Flow
1. User sends message via QQ
2. Bridge receives `C2C_MESSAGE_CREATE` event
3. Message sent to Claude via `tmux send-keys`
4. Claude processes and writes assistant text to `.jsonl`
5. Bridge's `periodic_poll()` reads new JSONL lines
6. Text pushed to QQ via API

### Approval Flow
1. Claude needs permission → writes `waitingFor: "permission prompt"` to session file
2. Bridge detects `waitingFor` in poll cycle
3. Bridge sends QQ approval card with buttons (✅ Allow / 🛡️ Always / ❌ Deny)
4. User clicks button on QQ
5. Callback received as text message `approve:default:allow|deny|allow_always`
6. Bridge sends keystroke (1/2/3) to tmux
7. Claude receives keystroke, proceeds or aborts
8. `waitingFor` clears → poll resumes normal cycle

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| JSONL over terminal capture | Structured log gives clean text, no ANSI control chars |
| Session file for approval | `waitingFor` field is a boolean — no text pattern matching |
| Two-message send (text + button) | QQ API doesn't render keyboard with mixed markdown content |
| polling over event-driven | Simple, reliable; 3s interval is good enough for chat |
| No subprocess stdout | Interactive mode in tmux avoids `--print` limitations |
| 5-min soft timeout | Long tasks (compile, download) should not be killed |

---

## Production History

- **Runtime**: Continuous operation on Tencent Cloud server
- **Architecture Iterations**: Multiple versions from stateless `--print` to interactive tmux
- **Key Fix**: Approval detection changed from terminal text matching (fragile) to session file `waitingFor` (structured)
