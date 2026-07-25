# Evidence Pack: AGY-QQ Bridge Orchestration Failure Modes

*Abridged from /root/AGY_BRIDGE_SNAPSHOT/*

---

## 1. Case Study Summary

*Full: /root/AGY_BRIDGE_SNAPSHOT/CASE_STUDY.md (8KB, 7 sections)*

Production bridge connecting AGY CLI to QQ. Ran 48+ hours across 7 architecture versions. Central finding: **no structured intermediate state exists** for approval/execution gating in AGY's transcript, forcing fragile terminal UI parsing.

---

## 2. Master Timeline Summary

*Full: /root/AGY_BRIDGE_SNAPSHOT/MASTER_TIMELINE.json (30+ events, 4 categories)*

| Phase | Key Event | Result |
|-------|-----------|--------|
| v0 (Jun 16) | Project init | First bridge script |
| v1 (Jun 26 15:29) | WS connected, first reply | Banner leaked as reply |
| v4.x (Jun 26 16:00) | English TUI keywords | Reduced false positives |
| v5.0 (Jun 26 17:30) | pipe-pane file reading | Control char pollution |
| v6.x (Jun 26 20:00) | Delimiter truncation | Variable-length breakage |
| v7.x (Jun 26 23:00) | Reader+Queue | TUI stale false positives |
| v8.0 (Jun 27 09:00) | transcript.jsonl primary | Architecture turning point |
| v8.1-8.2 (Jun 27 10:00) | TUI polling + pre-check + tail10 | Current stable (fragile) |
| v8.2 verified (Jun 27 11:00) | No PENDING states in transcript | System boundary confirmed |

---

## 3. Three Key Failure Modes

### F1: Terminal output is not a machine-readable data source
- capture-pane returns screen content + history + banners + control characters
- pipe-pane includes scrollback redraw artifacts
- Every parsing approach (watermark, offset, delimiter, pattern) introduces new fragility

### F2: Auto-approval creates undetectable TUI residue
- AGY in sandbox mode auto-approves commands silently
- Approval TUI text briefly appears then disappears (100-500ms window)
- Bridge cannot distinguish "stale TUI text" from "waiting for approval"
- 3 separate fixes reduced but did not eliminate false positives

### F3: No intermediate state layer in execution log
- transcript.jsonl records only `status=DONE`
- Zero entries with `status=PENDING`, `status=WAITING`, `status=APPROVAL_REQUIRED`
- External systems cannot determine whether AGY is thinking, waiting for approval, or already executing
- This is a structural property of the event model, not a bug

---

## 4. System Evolution (v4 → v8.2)

```
v4 [capture-pane + watermark line-diff]
 │   Problem: historical content leaks
 ▼
v5 [tmux pipe-pane + file offset]
 │   Problem: control chars + scrollback redraw
 ▼
v6 [pipe-pane + drain + delimiter truncation]
 │   Problem: variable delimiter length
 ▼
v7 [reader co-routine + asyncio.Queue]
 │   Problem: auto-approval TUI stale detection
 ▼
v8 [transcript.jsonl primary + capture-pane fallback]
 │   Problem: AGY reply contains approval keywords
 ▼
v8.2 [transcript pre-check + last-10-line scan]
     ──→ Stable but fragile ──→ architecture limitation confirmed
```

---

## Evidence Provenance

| Artifact | Location | Size |
|----------|----------|------|
| Code snapshots (v5-v8) | `/root/AGY_BRIDGE_SNAPSHOT/code_snapshot/` | 33-35KB each |
| Bridge log | `/root/AGY_BRIDGE_SNAPSHOT/logs_snapshot/agy-qq-bridge.log` | 80KB |
| Transcript sample | `/root/AGY_BRIDGE_SNAPSHOT/logs_snapshot/transcript_last500.jsonl` | 111KB |
| Runtime state | `/root/AGY_BRIDGE_SNAPSHOT/runtime_state/process_list.txt` | Active PID 4046885 |