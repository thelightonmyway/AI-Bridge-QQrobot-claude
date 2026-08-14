Daily Usage
===========

Chatting
--------

Send the bot a normal message and the bridge forwards it to Claude Code
running in tmux, then pushes the reply back to QQ.

Normal messages and ``/btw`` panel content are never sent to Bash by mistake —
a safeguard against unintended input.

Session persistence and auto-recovery
-------------------------------------

* The bridge only binds to the Claude process inside **its own tmux pane**,
  so it never binds a Claude running in another terminal (pane-scoped PID
  detection).
* If Claude exits unexpectedly, the bridge automatically resumes the session
  with ``--resume`` and re-binds the new PID.
* Use ``/resume`` to list historical sessions and restore a specific one
  (see :doc:`commands`).

Permission modes
----------------

Claude Code's permission modes cycle through ``Auto`` → ``Accept edits`` →
``Plan`` → ``Manual``. Switch with ``/mode`` (equivalent to pressing ``Tab``
in Claude); use ``/mode status`` to view the current mode.

Sending images / files
----------------------

Images and files come from a path **on the bridge host**, not from your phone
album:

.. code-block:: text

   /sendimg /path/to/screenshot.png
   /sendfile /path/to/report.pdf

Supported images: jpg / jpeg / png / webp (≤10 MB).
Supported files: pdf / docx / xlsx / pptx / txt / zip, and similar.

Session management
------------------

* ``/clear`` starts a new session;
* ``/compact`` compresses the current conversation to save tokens;
* ``/context`` shows the current context usage.

Multiple users
--------------

If ``MASTER_OPENID`` is empty, the first user who sends a message is
automatically bound as the Master. Only the Master user can control the
bridge.
