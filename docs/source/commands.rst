QQ Commands
===========

Send any of the following as a plain message to your bot.

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
     - Ask a side question without interrupting the main flow
   * - ``/pwd``
     -
     - Show the current working directory
   * - ``/ls [path]``
     -
     - List directory contents (up to 50 entries)

Command reference
-----------------

``/stop`` (aliases ``/tingzhi`` / ``/kill``)
    Interrupt the task Claude is currently working on. Claude stays alive —
    only the current generation is interrupted.

``/resume`` (aliases ``/huifu`` / ``/history``)
    List recent sessions for the current project; ``/resume N`` restores
    session N. With no argument, the 10 most recent sessions are shown. If a
    session's working directory cannot be determined, recovery is aborted
    protectively to avoid starting in the wrong directory.

``/cd <path>``
    Change Claude's working directory to the given absolute path.

``/sendimg <path>``
    Send a local image from the bridge host to QQ. Supported formats:
    jpg / jpeg / png / webp, up to 10 MB.

``/sendfile <path>``
    Send a local file from the bridge host to QQ. Supported formats:
    pdf / docx / xlsx / pptx / txt / zip, and similar.

``/mode``
    Switch Claude's permission mode, cycling through Auto → Accept edits →
    Plan → Manual. ``/mode status`` shows the current mode.

``/context``
    Show the current context usage (token count).

``/compact``
    Compress the current conversation to save tokens.

``/clear`` (aliases ``/new`` / ``/reset`` / ``/qingkong`` / ``/xin duihua``)
    Start a brand-new session.

``/btw <question>`` (alias ``/by-the-way``)
    Ask a side question without interrupting the current task. Claude answers
    it while the main task keeps running, and the full answer is sent back to
    QQ. Answers may take a few minutes to arrive; very long answers are
    delivered as a TXT file instead of being truncated.

``/pwd``
    Show Claude's current working directory.

``/ls [path]``
    List directory contents (up to 50 entries; hidden files are not shown).
    The path is optional and defaults to the current working directory.

Approval buttons
----------------

When Claude asks for permission to perform an action, your bot sends an
approval button: ``allow``, ``allow always``, or ``deny``. Tap it to respond
directly from QQ.
