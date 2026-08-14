Troubleshooting
===============

Check the log first
-------------------

All bridge logs are written to ``~/agent-keep/logs/bridge.log``. Most issues
are visible in the log:

.. code-block:: bash

   tail -f ~/agent-keep/logs/bridge.log

Bridge does not start
---------------------

Check whether the bridge process is running:

.. code-block:: bash

   ./start.sh status

If the process exited immediately, the log usually shows why. Restart the
bridge:

.. code-block:: bash

   ./start.sh restart

QQ bot does not respond
-----------------------

* Make sure the bridge is running: ``./start.sh status``.
* Check that ``APP_ID`` and ``CLIENT_SECRET`` in ``~/agent-keep/.env`` are
  correct.
* Confirm the bot has been approved and enabled for C2C messaging on the QQ
  Open Platform.
* Watch the log while you send a message:
  ``tail -f ~/agent-keep/logs/bridge.log``.

``command -v claude`` fails
---------------------------

Claude Code is not installed or not on ``PATH``. Install it and complete the
prerequisites in :doc:`quickstart` first.

Session recovery aborts with a working-directory warning
--------------------------------------------------------

When resuming an old session, the bridge aborts recovery protectively if it
cannot determine that session's working directory, to avoid starting in the
wrong directory. Send ``/resume`` to choose the session again.
