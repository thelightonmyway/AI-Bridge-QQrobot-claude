Installation
============

This page is a reference for setting up AI-Bridge-QQrobot-claude. If you are starting from
scratch, follow :doc:`quickstart` — the setup script automates most of it.

Prerequisites
-------------

* Python 3.10 or newer, with ``pip``
* ``tmux`` and ``git``
* the ``claude`` CLI (Claude Code)
* a QQ bot on the QQ Open Platform, with ``APP_ID`` and ``CLIENT_SECRET``

Configuration
-------------

All configuration lives in ``~/AI-Bridge-QQrobot-claude/.env``:

.. code-block:: ini

   APP_ID=YOUR_QQ_BOT_APP_ID
   CLIENT_SECRET=YOUR_QQ_BOT_CLIENT_SECRET
   MASTER_OPENID=
   TMUX_SESSION=1

* ``APP_ID`` / ``CLIENT_SECRET`` — your QQ bot credentials (required).
* ``MASTER_OPENID`` — the OpenID of the user allowed to control the bridge.
  Leave empty to auto-bind the first user who sends a message.
* ``TMUX_SESSION`` — the tmux session number the bridge attaches to
  (default: ``1``).

The bridge also looks for a ``.env`` file in the current working directory
and inside ``packages/claude-code-qq-bridge/``, but ``~/AI-Bridge-QQrobot-claude/.env`` is
the canonical location.

Managing the bridge
-------------------

The ``start.sh`` script controls the bridge process:

.. code-block:: bash

   ./start.sh start      # start the bridge in the background
   ./start.sh status     # show whether it is running
   ./start.sh restart    # restart it
   ./start.sh stop       # stop it

Logs are written to ``~/AI-Bridge-QQrobot-claude/logs/bridge.log``. The PID of the running
bridge is recorded in ``~/AI-Bridge-QQrobot-claude/logs/bridge.pid``.

Verify the setup
----------------

Send your bot a plain message from QQ. If you receive a reply from Claude,
everything is working. You can also confirm the process is alive:

.. code-block:: bash

   ./start.sh status
