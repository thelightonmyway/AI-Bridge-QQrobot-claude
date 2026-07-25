# AGY-QQ Bridge — Case Study

*Document generated: 2026-06-27 | Source: /root/AGY_BRIDGE_SNAPSHOT/*

---

## 1. Executive Summary

We built a production bridge connecting Google's Antigravity CLI (AGY) to QQ messaging platform, enabling remote mobile control of a CLI agent. The bridge operates at v8.2 after 7 major architecture iterations across 48+ hours of runtime. The central finding: AGY's CLI agent runtime lacks structured intermediate state exposure required for external orchestration systems — specifically, no machine-readable approval pending events exist in its execution log, forcing the bridge to rely on fragile terminal UI parsing (capture-pane) that cannot be made reliable.

---

## 2. System Architecture

```
┌─────────────────────┐     ┌──────────────────────────────────┐     ┌─────────────────────┐
│   QQ Input Layer    │     │        Bridge Layer (Python)     │     │   AGY Runtime Layer │
│                     │     │                                  │     │                     │
│  User sends message │────>│  send_to_agy(): tmux send-keys   │────>│  tmux session (agy) │
│                     │     │                                  │     │                     │
│  Receive reply      │<────│  wait_for_agy_response():        │<────│  transcript.jsonl   │
│                     │     │    - transcript.jsonl (primary)   │     │  (PLANNER_RESPONSE) │
│  Approval buttons   │<────│    - capture-pane TUI (fallback)  │<────│  TUI (approval)     │
│                     │     │                                  │     │                     │
│  Button click       │────>│  handle_approval_action():       │────>│  send keystroke     │
└─────────────────────┘     │    send keystroke to tmux        │     └─────────────────────┘
                            └──────────────────────────────────┘
```

**Data sources (read):**
- `transcript.jsonl` — AGY brain structured log (`source=MODEL, type=PLANNER_RESPONSE, status=DONE`)
- `capture-pane` — terminal screen capture for TUI detection only

**Control path (write):**
- `tmux send-keys` — injected keystrokes for approval decisions (y/a/p/n)

**Production runtime:** 48+ hours, single server (Tencent Cloud 110.40.140.85), PID 4046885

---

## 3. Observed Failure Modes

*Referenced from ISSUES_RAW.json (see /root/AGY_BRIDGE_SNAPSHOT/ISSUES_RAW.json for full facts)*

### Data Layer Issues (capture-pane / pipe-pane)

| ID | Symptom | Duration |
|----|---------|----------|
| ISSUE-001 | CLI startup banner leaked as reply | v1-v4 |
| ISSUE-002 | Historical conversation appended to current reply | v1-v4 |
| ISSUE-005 | Control characters in pipe-pane output broke parsing | v5 |
| ISSUE-006 | Incremental pipe-pane reads lost content due to scrollback redraw | v5-v6 |
| ISSUE-007 | Variable-length delimiter caused truncation errors | v6 |

**Pattern:** Every approach to reading AGY's terminal output introduced new data corruption vectors. Watermark line-diff (v4), pipe-pane file offset (v5), delimiter truncation (v6), reader+queue (v7) — each solved the previous problem but created a new one. The only stable approach was transcript.jsonl (v8), but this only covers completed execution, not intermediate states.

### Control Layer Issues (approval / TUI)

| ID | Symptom | Duration |
|----|---------|----------|
| ISSUE-003 | AGY reply containing Chinese keywords triggered false approval | v4.x |
| ISSUE-004 | AGY discussing permission concepts triggered false approval | v4.x |
| ISSUE-008 | AGY auto-approved in sandbox but TUI text lingered, bridge sent false buttons | v7-v8.0 |
| ISSUE-009 | AGY reply containing English approval keywords triggered false approval | v8.0-v8.1 |

**Pattern:** The bridge cannot distinguish between "AGY is waiting for user approval" and "AGY's output contains discussion about approvals." Three separate fixes (English keywords only, TUI disappearance polling, transcript pre-check, last-10-line scan) each reduced but never eliminated false positives.

### State Layer Issues (no pending state)

| ID | Symptom | Severity |
|----|---------|----------|
| ISSUE-010 | transcript.jsonl contains zero PENDING/WAITING/APPROVAL states | Architecture limitation |

**Pattern:** All PLANNER_RESPONSE entries carry `status=DONE`. There is no `status=PENDING` or `status=WAITING_APPROVAL` or equivalent. The execution log is purely post-hoc — it records what *happened*, not what *is waiting to happen*. This is not a bug; it is a structural property of AGY's event model.

---

## 4. Key Finding

> CLI agent runtime lacks structured intermediate state exposure required for external orchestration systems.

Specifically: AGY's transcript.jsonl records execution outcomes (`PLANNER_RESPONSE, status=DONE`) but produces zero events for intermediate states such as "approval requested," "tool execution pending," or "waiting for user input." External systems (QQ bridge, CI/CD pipelines, headless deployments) are forced to infer these states from terminal UI text — an inherently unreliable method that has resisted stabilization across 7 architecture iterations.

---

## 5. Evidence Strength

| Metric | Value |
|--------|-------|
| Runtime hours | 48+ hours continuous |
| Architecture iterations | 7 major versions (v4 → v8.2) |
| Recorded events | 30+ in Master Timeline |
| Code snapshots | 5 versions preserved |
| Transcript entries | 250+ PLANNER_RESPONSE events analyzed |
| Failed approaches | 6 distinct failure modes documented |
| Production environment | Real QQ bot, real user, Tencent Cloud server |
| Repository | `github.com/zz327455573/agent_qqbot_bridge`, commit `6f8e182` |

---

## 6. Implication

*Facts only — no speculative conclusions.*

1. **UI parsing is a non-convergent path.** Each of 7 architecture iterations (capture-pane watermark → pipe-pane → delimiter → reader+queue → transcript → hybrid TUI detection) introduced new fragility. Terminal output was designed for human reading, not machine parsing. No amount of regex, offset tracking, or timeout tuning can make it as reliable as a structured event stream.

2. **CLI agents without structured intermediate state cannot be safely orchestrated by external systems.** When the orchestrator cannot distinguish "waiting for approval" from "auto-approved and running" from "reply contains discussion about approvals," it cannot make correct control decisions. The result is either false positives (users asked to approve already-executed commands) or false negatives (approvals missed).

3. **The required abstraction exists in adjacent systems.** Transcript.jsonl already provides structured execution output (`source=MODEL, type=PLANNER_RESPONSE, status=DONE`). Extending this to cover intermediate states (`type=APPROVAL_PENDING`, `type=TOOL_PRE_EXEC`) would require no new infrastructure — only an additional event type in the existing log format. The `--dangerously-skip-permissions` flag proves Google recognizes the automation use case; the missing piece is observability, not bypass.

---

## 7. Non-Scope

This document explicitly does NOT address:

❌ How to fix capture-pane reading
❌ Alternative TUI detection strategies (OCR, heuristics, ML classification)
❌ New bridge architecture proposals (wrapper agents, webhook interceptors, proxy layers)
❌ Code optimization or refactoring of QQ bridge
❌ Comparison of tmux vs PTY vs direct subprocess control
❌ Feature requests or design proposals for AGY CLI

---

*Sources: /root/AGY_BRIDGE_SNAPSHOT/MASTER_TIMELINE.json, ISSUES_RAW.json, SYSTEM_BOUNDARY.md, runtime_state/system_state.json*
