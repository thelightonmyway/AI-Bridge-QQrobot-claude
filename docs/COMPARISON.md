# Comparison: Agent Keep vs. Other Approaches

## Detailed Comparison Table

| Aspect | Agent Keep | Typical IM Bridge | API-based Agent | SSH + tmux (manual) |
|--------|-----------|-------------------|-----------------|---------------------|
| **Session persistence** | ✅ True persistent (tmux/ConPTY) | ❌ Ephemeral (per-request) | ❌ Ephemeral | ✅ Persistent |
| **Context management** | ✅ Agent manages naturally | ❌ Bridge manages history | ❌ API manages | ✅ Agent manages |
| **Tool access** | ✅ Full CLI/terminal/desktop | ❌ Limited by API | ❌ Sandboxed | ✅ Full |
| **Multi-agent** | ✅ 3+ simultaneously | ❌ Usually 1 | ✅ Easy | ❌ Manual tmux switching |
| **Windows support** | ✅ ConPTY + desktop API direct-connect | ❌ Linux only | ✅ API-based | ❌ SSH-only |
| **Approval flow** | ✅ QQ card buttons | ❌ No | ✅ API-based | ❌ Manual |
| **Long tasks** | ✅ No timeout | ❌ Timeout issues | ✅ API handles | ✅ No timeout |
| **Remote access** | ✅ Phone → QQ/WeChat | ✅ Phone → IM | ✅ Anywhere | ❌ SSH only |
| **Setup complexity** | ⭐⭐ (pip install + .env) | ⭐⭐ (similar) | ⭐⭐⭐ (API keys) | ⭐ (SSH + tmux) |
| **Production-ready** | ✅ Running for months | ❌ Mostly experimental | ✅ Enterprise-grade | ✅ Manual |

## What Makes Agent Keep Different

### 1. It's Not an IM Bridge — It's an Agent Gateway

The term "IM bridge" is misleading. It suggests a simple protocol translator. Agent Keep is a **persistent agent gateway** that:

- Keeps agents alive 24/7 (not per-request)
- Manages agent lifecycles (start, stop, restart, health check)
- Provides session state awareness (approval detection, output streaming)
- Is channel-agnostic (QQ is the first implementation)

### 2. True Persistent Sessions

Most "IM + AI" projects use this pattern:

```
[User] → [IM Bridge] → [Start CLI process] → [Send prompt] → [Get output] → [Kill process]
```

This means every request is cold-start. The agent has no memory of previous interactions unless the bridge manually stitches together conversation history.

Agent Keep uses this pattern:

```
[Agent lives in tmux/ConPTY 24/7]
[User] → [IM Bridge] → [Inject message into agent session] → [Agent continues naturally]
```

The agent manages its own context. It remembers what it was doing. It has access to the same filesystem, terminal, and tools across sessions.

### 3. Multi-Platform, Multi-Agent

Most projects target a single agent (usually Claude Code) on a single platform (Linux). Agent Keep covers:

**Agents:**
- Claude Code (Linux)
- Codex CLI (Linux)
- Google Antigravity (Linux)
- Google Antigravity Desktop (Windows)

**Platforms:**
- Linux (tmux-based)
- Windows (ConPTY-based)

**Channels:**
- QQ (reference implementation)
- WeChat, Telegram, Feishu, Discord (architecture ready, adapters needed)

### 4. Production-Proven

These bridges have been running in production for months:
- Processing real user requests daily
- Surviving agent crashes, network interruptions, and restarts
- Handling edge cases (approval flows, multi-part responses, session resets)
- The code is pip-installable and tested

## Common Misconceptions

### "It's just a wrapper around tmux"

Yes, it uses tmux. But so does every production deployment of Claude Code or Codex. The value isn't in the tmux wrapper — it's in:

1. **Automated message injection** — Escape key press to close popups, clean input, proper timing
2. **Structured output capture** — JSONL log reading instead of terminal scraping (no ANSI, no control chars)
3. **State detection** — Knowing when the agent is waiting for approval vs. working vs. done
4. **Lifecycle management** — Auto-restart, health checks, session reset
5. **Channel integration** — QQ Bot API, eventually multi-channel

### "Why not just use SSH?"

SSH works if you're at your desk. Agent Keep is for when you're:
- Away from your computer
- Checking on long-running tasks
- Wanting to quickly ask a question without opening a terminal
- Needing to control a Windows machine remotely

### "There are already projects like this"

There are many IM bridges, but most are:
- Single-channel (Feishu or Telegram only)
- Single-agent (Claude Code only)
- Resume-based (not truly persistent)
- Experimental (not production-tested)

Agent Keep's key differentiators are: **multi-agent, multi-platform, truly persistent, production-proven.**