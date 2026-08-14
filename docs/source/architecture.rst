Architecture
============

Data flow
---------

.. code-block:: text

   QQ user ──> QQ bot WebSocket ──> bridge ──> tmux send-keys ──> Claude Code
      ▲                                                            │
      └────────── QQ messages / approval buttons ◄──────── capture replies ◄─┘

Claude Code's input and output are an interactive terminal. The bridge works
with it through two **independent channels**:

1. **Session file channel**: reads Claude's session state (such as
   ``waitingFor``) and renders the approval buttons on QQ from it;
2. **JSONL channel**: reads Claude's conversation JSONL and pushes assistant
   text to QQ as replies.

When a QQ button is clicked, the bridge sends the corresponding key back to
Claude via ``tmux send-keys`` (for example 1/2/3 for approval, ``BTab`` for
``/mode``) so the task can continue.

Design principles
-----------------

* **Single live session**: only one active Claude session is maintained at a
  time;
* **Reads only fixed structural fields, no content analysis**: the bridge
  parses only the fixed fields of the session/JSONL files, never the
  conversation content;
* **Independent dual channels**: session state and JSONL do not depend on
  each other;
* **Cache used only for restart detection**: no state machine is maintained;
* **No group messages**: only C2C (single-chat) messages are handled;
* **No futures / state machines**.

Modules
-------

Under ``packages/claude-code-qq-bridge/``:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - File
     - Role
   * - ``src/claude_code_qq_bridge/bridge.py``
     - Main program: QQ WebSocket, tmux driver, session recovery, command
       dispatch, media sending, and approval buttons. Entry point:
       :func:`~claude_code_qq_bridge.bridge.cli`.
   * - ``claude-conversation-monitor.py``
     - Standalone session monitor: polls the Claude JSONL and writes the
       conversation to the shell-snapshots log.
   * - ``claude-code-qq-bridge.py``
     - Top-level standalone entry point (equivalent to the package entry).
   * - ``start.sh`` (repository root)
     - Bridge lifecycle management: start / stop / restart / status, with all
       logs collected in ``~/agent-keep/logs/bridge.log``.

Session recovery
----------------

* **Pane-scoped PID detection**: the bridge finds the Claude process inside
  **its own tmux pane** instead of matching ``claude`` globally, avoiding
  accidental binding to a Claude running in another terminal;
* **Automatic ``--resume``**: when Claude exits unexpectedly, the bridge
  restarts it with ``--resume <session>`` and re-binds the new PID;
* **Mis-send guard**: ``/btw`` panel content and plain messages are never
  sent to Bash while Claude is not alive (the ``_pane_has_claude()`` guard,
  plus a ``cwd`` check before ``/resume N``).

QQ side
-------

* Obtains a token via ``getAppAccessToken`` from ``bots.qq.com`` (cached and
  refreshed before expiry);
* Opens a WebSocket through the gateway, with heartbeat and reconnection
  (2s → 60s backoff);
* Dispatches messages and events through ``handle_c2c_message`` /
  ``handle_interaction``;
* Uploads images / files to QQ to get a URL, then sends them as rich-media
  messages.

Deployment layout
-----------------

.. code-block:: text

   ~/agent-keep/
   ├── .env                  # APP_ID / CLIENT_SECRET / MASTER_OPENID / TMUX_SESSION
   ├── start.sh              # start / stop / restart / status
   ├── setup.sh              # one-click setup script (see Quick Start)
   ├── logs/bridge.log       # unified log
   └── packages/claude-code-qq-bridge/   # core package
