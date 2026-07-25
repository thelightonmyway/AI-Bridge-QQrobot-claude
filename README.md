# Agent Keep 🏠

> Keep your CLI agents alive. 24/7. From your phone.

[![GitHub](https://img.shields.io/badge/agents-Claude%20Code%20%7C%20Codex%20%7C%20AGY-blue)](https://github.com/zz327455573/agent-keep)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20Windows-green)]()
[![Channel](https://img.shields.io/badge/channel-QQ-orange)]()

[🇨🇳 中文版](README.zh-CN.md)

---

## What is this?

**Not another IM bridge. This is a persistent agent gateway.**

Most "IM to AI" projects work like this:

```
User message → Start a process → Send prompt → Get response → Kill process
```

**Agent Keep works differently:**

```
Agent lives in tmux → 24/7 online → Phone sends message → 
Agent does real work (files, terminal, browser, desktop) → 
Responds with results → Context stays alive
```

**The difference is fundamental:**

| Typical IM Bridge | Agent Keep |
|:--|:--|
| Agent starts fresh every request | **Agent lives in tmux/ConPTY 24/7** |
| Bridge manages conversation history | **Agent manages its own session naturally** |
| Limited to API-accessible tools | **Full CLI, terminal, browser, desktop access** |
| Timeout on long tasks | **Always-on, no timeout** |
| One agent at a time | **3+ agents running simultaneously** |
| No Windows support | **✅ Windows desktop API direct-connect** |

---

## The 4 Bridges

Each bridge is a standalone, pip-installable package. Pick the agents you use.

## Repository Layout

This repository now contains real bridge source code under [`packages/`](./packages):

- `packages/claude-code-qq-bridge/`
- `packages/codex-qq-bridge/`
- `packages/agy-qq-bridge/`

The top-level repo is the umbrella monorepo. Each bridge package keeps its own Python package metadata, entrypoints, and docs.

### 1. [Claude Code QQ Bridge](https://github.com/zz327455573/claude-code-qq-bridge)
`claude-code-qq-bridge` — The most mature bridge.
- ✅ Approval buttons via QQ card messages
- ✅ Session state monitoring (`waitingFor` detection)
- ✅ JSONL incremental log reading (no ANSI garbage)
- ✅ Auto-restart on crash, single-session keep-alive

### 2. [Codex QQ Bridge](https://github.com/zz327455573/codex-qq-bridge)
`codex-qq-bridge` — Simple, clean, multi-turn.
- ✅ Multi-turn conversation with session continuation
- ✅ Adaptive JSONL file binding
- ✅ No approval interception (Codex handles it natively)

### 3. [AGY QQ Bridge (Linux)](https://github.com/zz327455573/AGY-QQ-Bridge)
`agy-qq-bridge` — Async log monitoring for Google Antigravity.
- ✅ Fully async, no busy locks
- ✅ Multi-part response support (one input → many replies)
- ✅ Adaptive session file binding on `/new`

### 4. [Antigravity QQ Bridge (Windows)](https://github.com/zz327455573/Antigravity-QQ-Bridge-Win)
`antigravity-qq-bridge-win` — Windows desktop remote AI workstation.
- ✅ Direct API connection to `language_server.exe` (no PTY/ConPTY needed)
- ✅ Dynamic process discovery (auto-detect port + CSRF token)
- ✅ Model auto-sync from desktop GUI (`settings.json`)
- ✅ Session persistence (`conversation_id` survives restarts)
- ✅ UTF-8 forced output (no GBK crash on emoji)

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  Your Phone                        │
│              (QQ / WeChat / Telegram / etc.)       │
└──────────┬───────────────────────┬────────────────┘
           │                       │
           ▼                       ▼
┌──────────────────────────────────────────────────┐
│          Agent Gateway (Bridge Layer)              │
│                                                    │
│  ┌──────────────┐    ┌──────────────┐              │
│  │  Channel: QQ │    │ Channel: ... │  ← Adapter   │
│  │  (reference) │    │ (next)       │   pattern    │
│  └──────┬───────┘    └──────┬───────┘              │
│         │                   │                       │
│         ▼                   ▼                       │
│  ┌────────────────────────────────────────┐        │
│  │         Runtime Layer                   │        │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │        │
│  │  │ tmux │ │ConPTY│ │ JSONL│ │Session│  │        │
│  │  │      │ │      │ │ Log  │ │State  │  │        │
│  │  └──┬───┘ └──┬───┘ └──┬───┘ └──┬────┘  │        │
│  └─────┼────────┼────────┼────────┼────────┘        │
└────────┼────────┼────────┼────────┼─────────────────┘
         │        │        │        │
         ▼        ▼        ▼        ▼
┌──────────────────────────────────────────────────┐
│   Claude Code  │  Codex  │  AGY  │  AGY (Win)    │
│   (24/7 alive)  │ (24/7)  │ (24/7) │  (24/7)      │
└──────────────────────────────────────────────────┘
         │         │        │        │
         ▼         ▼        ▼        ▼
┌──────────────────────────────────────────────────┐
│         Computer Environment                      │
│  (Files, Terminal, Browser, Desktop Automation)    │
└──────────────────────────────────────────────────┘
```

### Key Design Principle: Channel Abstraction

Each bridge is a **channel adapter** + **agent adapter**:

```
┌─────────────────────────────┐
│        Bridge                │
│  ┌───────────┐ ┌─────────┐  │
│  │ Channel   │ │ Agent   │  │
│  │ Adapter   │ │ Adapter │  │
│  │           │ │         │  │
│  │ • QQ WS   │ │ • tmux  │  │
│  │ • WeChat  │ │ • ConPTY│  │
│  │ • Telegram│ │ • PTY   │  │
│  │ • Discord │ │         │  │
│  └───────────┘ └─────────┘  │
└─────────────────────────────┘
```

**QQ is the reference implementation.** Switching to WeChat, Telegram, or Discord means changing the channel adapter only — the agent runtime, session management, and output capture stay the same.

---

## Why this matters

### For individuals
You're running Claude Code / Codex / AGY on your server. You SSH in, type commands, wait. Can't check on long tasks from your phone. Context gets lost when you disconnect.

**With Agent Keep:**
- Open QQ → Type "帮我检查服务器" → Done → Reply comes back
- Long-running task? Send a message anytime, it replies when ready
- New session? `/new` resets, bridge auto-reconnects

### For teams
- Multiple agents running simultaneously on the same machine
- Each agent has its own persistent session, never cross-contaminated
- Windows machine acts as a remote AI workstation (browser, desktop, file ops)

### For developers
- Full CLI tool access — not limited by API sandboxing
- Agents can install packages, edit files, run scripts, control browsers
- True persistent sessions mean no context window rebuilding

---

## Quick Start

```bash
# Clone the monorepo
git clone https://github.com/zz327455573/agent-keep.git
cd agent-keep

# Pick any bridge package, install with pip:
pip install ./packages/claude-code-qq-bridge

# Or install another bridge package:
pip install ./packages/codex-qq-bridge
pip install ./packages/agy-qq-bridge

# Initialize (only asks for QQ Bot credentials)
claude-code-qq-bridge --init

# Run
claude-code-qq-bridge
```

Detailed instructions in each bridge's README.

---

## Comparison: Agent Keep vs. Other Approaches

### vs. "IM Bridge" (resume/replay pattern)
Most bridges start a new CLI process for each message, feed it the conversation history, and kill it after. This means:
- Every request reloads the full context (slow, expensive)
- Agent has no persistent state
- No ongoing tool access

### vs. API-based solutions (OpenAI API, etc.)
API-based agents are sandboxed — they can't touch your files, run local scripts, or control your browser.

### vs. SSH + tmux (manual)
Agent Keep **is** SSH + tmux, but automated. You don't need to SSH in, attach to a session, type commands, and watch output. The bridge handles all of that.

---

## Roadmap

- [ ] **WeChat / Enterprise WeChat** channel adapter
- [ ] **Telegram** channel adapter
- [ ] **Feishu / Lark** channel adapter
- [ ] **Discord** channel adapter
- [ ] Unified CLI: `agent-keep start claude`
- [ ] Web dashboard: view all agents, session logs
- [ ] Multi-user support
- [ ] Docker deployment

---

## Philosophy

CLI agents are the most capable AI tools we have. They run on our machines, have access to everything, and can do real work. The only thing missing is **persistence** — they're stuck in a terminal, tied to an SSH session.

**Agent Keep fixes that.** It gives your agents a permanent home where they live, work, and wait for your instructions. From anywhere. From your phone.

---

## License

MIT. Each bridge is independently licensed under MIT.

---

**Made by [@zz327455573](https://github.com/zz327455573)** — 竹山文达门窗 / 个人AI Agent在线化
