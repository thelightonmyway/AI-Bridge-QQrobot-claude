Session Management
==================

A *session* is a Claude Code conversation running in a tmux pane, managed by
the bridge.

Automatic recovery
------------------

If Claude exits or crashes, the bridge automatically restarts it with
``--resume`` and re-binds to the recovered process, so your conversation is
not lost. The bridge only manages the Claude inside its own tmux pane and
never interferes with Claude running elsewhere.

Switch sessions
---------------

* ``/resume`` — list recent sessions for the current project; ``/resume N``
  restores session N.
* ``/clear`` (or ``/new``) — start a brand-new session.

Manage the current conversation
-------------------------------

* ``/compact`` — compress the current conversation to save tokens.
* ``/context`` — show the current context usage.
* ``/mode`` — change Claude's permission mode.

See :doc:`commands` for the full command reference.
