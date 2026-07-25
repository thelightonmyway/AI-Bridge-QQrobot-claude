# Product Feedback: CLI Agent Structured State Observability

**Product:** Antigravity CLI (AGY) / Gemini CLI
**Submitted by:** Production integration case study
**Date:** 2026-06-27

---

## Problem Statement

CLI agents currently lack structured intermediate execution state exposure. The execution log (`transcript.jsonl`) records only final states (`PLANNER_RESPONSE, status=DONE`). There is no equivalent for intermediate states such as `APPROVAL_PENDING`, `TOOL_PRE_EXEC`, or `WAITING_USER_INPUT`. This forces any external orchestration system to infer agent state from terminal UI text — an approach that cannot be made reliable.

---

## Reproduction

A production bridge connecting AGY to QQ messaging platform was built and run for 48+ hours across 7 architecture iterations (v4→v8.2):

1. User sends command via QQ
2. Bridge forwards to AGY via `tmux send-keys`
3. AGY decides to execute a tool → approval TUI appears
4. If AGY's sandbox auto-approves (trusted environment), TUI disappears in ~100-500ms
5. Bridge polls `transcript.jsonl` — finds `status=DONE` (execution already completed)
6. If bridge uses `capture-pane` for TUI detection, stale TUI text or AGY's own discussion of approvals triggers false positives
7. Result: approval buttons sent to user for a command that was already executed

**Repository:** `github.com/zz327455573/agent_qqbot_bridge`
**Full evidence:** Available on request (20 files, 472KB — event timeline, 6 failure modes, system boundary analysis)

---

## Limitation

The root limitation is architectural, not a parsing issue:

- `transcript.jsonl` schema supports structured events but defines no intermediate state type
- AGY's approval flow has no machine-readable counterpart — the TUI is a visual affordance for humans only
- External systems cannot determine whether AGY is: thinking, waiting for approval, auto-approved and executing, or waiting for user input
- The existing `--dangerously-skip-permissions` flag confirms the automation use case is recognized, but offers only a binary bypass — no observable participation

---

## Impact

Any external system that needs to safely orchestrate a CLI agent must either:
- **Blindly approve all actions** (loss of control, defeats the purpose of approval gating)
- **Parse terminal UI** (non-convergent — 7 different parsing approaches all failed in production)
- **Add a human-in-the-loop at the external system level** (forces the user to switch between two interfaces)

Use cases affected: mobile remote control, CI/CD pipeline integration, headless deployment, multi-agent orchestration, automated incident response.

---

## Suggestion

Add a structured intermediate state event type to the existing `transcript.jsonl` schema:

```json
{"type": "APPROVAL_PENDING", "tool": "run_command", "command": "...", "status": "PENDING", "timestamp": "..."}
{"type": "APPROVAL_RESOLVED", "decision": "allow", "status": "DONE", "timestamp": "..."}
```

This does NOT change the security model:
- Human still makes the decision
- Approval bypass (`--dangerously-skip-permissions`) remains unchanged
- No new access pathways are created

It only makes the approval process **observable** to external systems — the same way `PLANNER_RESPONSE` already makes execution results observable.

---

*This feedback is based on a production system with 48+ hours runtime, 7 architecture iterations, 6 documented failure modes, and 250+ analyzed transcript events.*