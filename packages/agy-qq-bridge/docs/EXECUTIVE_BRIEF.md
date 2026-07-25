# Executive Brief: CLI Agent Orchestration — Structural Gap in Intermediate State Exposure

*Generated: 2026-06-27 | 1 page*

---

## 1. What Was Built

A production bridge connecting Google's Antigravity CLI (AGY) to QQ messaging platform. The system enables remote mobile control of a CLI agent: users send commands via QQ, the bridge forwards them through tmux to AGY, receives structured execution logs via `transcript.jsonl`, and surfaces approval decisions as interactive buttons.

**Duration:** 48+ hours production runtime | **Iterations:** 7 major versions (v4 → v8.2) | **Environment:** Tencent Cloud server, real user interaction

---

## 2. Structural Gap Identified

After 7 architecture iterations and 6 documented failure modes, one root cause recurs:

> **CLI agents currently lack structured intermediate state exposure required for external orchestration systems.**

**Specifically:** AGY's `transcript.jsonl` records only final execution states (`PLANNER_RESPONSE, status=DONE`). There is no equivalent for intermediate states such as `APPROVAL_PENDING`, `TOOL_PRE_EXEC`, or `WAITING_USER_INPUT`. External systems are forced to infer these states from terminal UI text (capture-pane) — an approach that proved fragile across all 7 iterations:

| Approach | Problem |
|----------|---------|
| Watermark line-diff (v4) | Historical content leaked into replies |
| pipe-pane file offset (v5) | Control characters + scrollback redraw broke reads |
| Delimiter truncation (v6) | Variable-length split points caused message loss |
| Reader+Queue (v7) | TUI stale detection failed on auto-approval |
| transcript + TUI hybrid (v8-v8.2) | False positives persist when AGY discusses approvals |

---

## 3. Why This Is a Product-Level Gap, Not a Bug

| This is NOT | This IS |
|-------------|---------|
| A parsing bug in the bridge | An absent event type in the agent runtime |
| A TUI design issue | A missing abstraction: structured intermediate state |
| A failure of capture-pane | A failure of observability surface |
| Fixable by better regex/timing | Requires addition of `status=PENDING` event type |

The existing infrastructure (`transcript.jsonl`, event schema) already supports structured logs. No new system is needed — only an additional event type (`type=APPROVAL_PENDING`, `status=PENDING`) in the same log stream. The `--dangerously-skip-permissions` flag confirms Google recognizes the automation use case; what is missing is **observability** of that process, not the ability to skip it.

**Key evidence:** All 250+ `PLANNER_RESPONSE` entries in the production transcript carry `status=DONE`. Zero entries carry `status=PENDING` or equivalent. The approval TUI is a visual affordance for humans — it has no machine-readable counterpart.

---

*Source: /root/AGY_BRIDGE_SNAPSHOT/CASE_STUDY.md — 7 sections, 8KB, production data*