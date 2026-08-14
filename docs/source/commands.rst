QQ Bot Commands
===============

Commands are dispatched in ``handle_c2c_message()``. The table below lists
every command supported by the current code, in alphabetical order, together
with its aliases.

Command overview
----------------

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Command
     - Aliases
     - Description
   * - ``/stop``
     - ``/tingzhi`` ``/kill``
     - Interrupt the current task
   * - ``/resume``
     - ``/huifu`` ``/history``
     - List historical sessions; ``/resume N`` restores session N
   * - ``/cd <path>``
     -
     - Change Claude's working directory
   * - ``/sendimg <path>``
     -
     - Send a local image from the bridge host
   * - ``/sendfile <path>``
     -
     - Send a local file from the bridge host
   * - ``/mode``
     -
     - Switch the permission mode; ``/mode status`` shows the current mode
   * - ``/context``
     -
     - Show current context usage
   * - ``/compact``
     -
     - Compress the current conversation
   * - ``/clear``
     - ``/new`` ``/reset`` ``/qingkong`` ``/xin duihua``
     - Start a new session
   * - ``/btw <question>``
     - ``/by-the-way``
     - Ask a "by the way" question (answered in the local panel without interrupting the main flow)
   * - ``/pwd``
     -
     - Show the current working directory
   * - ``/ls [path]``
     -
     - List directory contents (up to 50 entries)

Command reference
-----------------

``/stop`` (aliases ``/tingzhi`` / ``/kill``)
    **Purpose**: interrupt the task Claude is currently working on.
    **Arguments**: none.
    **Example**: ``/stop``
    **Notes**: handled directly by the bridge without passing through Claude,
    and does not kill the Claude process itself — Claude stays alive, only
    the current generation is interrupted. Replies ``⛔ Interrupted.``.

``/resume`` (aliases ``/huifu`` / ``/history``)
    **Purpose**: list historical sessions for the current project; ``/resume
    N`` restores the Nth one.
    **Arguments**: no argument lists the 10 most recent sessions (with
    number, time, size, tokens, and title); a number restores the matching
    session.
    **Example**: ``/resume`` shows the session list; ``/resume 1`` restores
    the first session in the list.
    **Notes**: before restoring, the real ``cwd`` is parsed from the target
    session's JSONL. Recovery is aborted if it cannot be resolved (to avoid
    starting in the wrong directory). Restoring holds ``_cmd_lock``.

``/cd <path>``
    **Purpose**: change Claude's working directory.
    **Arguments**: an absolute path.
    **Example**: ``/cd /path/to/project``
    **Notes**: handled locally by the bridge (holding the lock), not by
    Claude.

``/sendimg <path>``
    **Purpose**: send an image from the bridge host to Claude.
    **Arguments**: an absolute path to an image on the host (jpg / jpeg / png
    / webp, ≤10 MB).
    **Example**: ``/sendimg /path/to/screenshot.png``

``/sendfile <path>``
    **Purpose**: send a file from the bridge host to Claude.
    **Arguments**: an absolute path to a file on the host (pdf / docx / xlsx
    / pptx / txt / zip, and similar).
    **Example**: ``/sendfile /path/to/report.pdf``

``/mode``
    **Purpose**: switch Claude's permission mode; ``/mode status`` only
    queries the current mode.
    **Arguments**: no argument cycles through ``Auto → Accept edits → Plan →
    Manual``; ``status`` queries the current mode.
    **Example**: ``/mode`` switches to the next mode; ``/mode status`` shows
    the current mode and its source (Claude session / bridge tracking /
    capture-pane).
    **Notes**: the switch is performed by sending ``BTab`` to tmux, then
    verified with ``capture-pane`` when possible.

``/context``
    **Purpose**: show current context usage (token count).
    **Arguments**: none.
    **Notes**: sends the ``/context`` TUI command to Claude and parses its
    output.

``/compact``
    **Purpose**: compress the current conversation to save tokens.
    **Arguments**: none.
    **Notes**: sends ``/compact`` to Claude.

``/clear`` (aliases ``/new`` / ``/reset`` / ``/qingkong`` / ``/xin duihua``)
    **Purpose**: start a brand-new session.
    **Arguments**: none.

``/btw <question>`` (alias ``/by-the-way``)
    **Purpose**: ask a question unrelated to the main task; the answer is
    given by Claude in the local panel without interrupting the main flow.
    **Arguments**: the question text.
    **Example**: ``/btw What's the weather in Beijing today?``

``/pwd``
    **Purpose**: show Claude's current working directory.
    **Arguments**: none.

``/ls [path]``
    **Purpose**: list directory contents, handled locally without passing
    through Claude.
    **Arguments**: an optional path; defaults to the current working
    directory.
    **Example**: ``/ls``, ``/ls /etc``
    **Notes**: hidden files are not shown; at most 50 entries are listed, and
    any remainder is reported.

Approval buttons (``approve:``)
    When Claude requests approval, QQ receives a button. Clicking it makes
    the bridge send the corresponding key to tmux: ``allow`` = 1,
    ``allow_always`` = 2, ``deny`` = 3.
    **Notes**: keys are sent only when Claude is actually alive in the pane,
    to avoid sending them to Bash by mistake.
