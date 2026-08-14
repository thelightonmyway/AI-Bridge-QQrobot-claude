Installation
============

This page is for users who already have the repository and want to run the
bridge on their own machine. For a one-click setup from scratch, see
:doc:`quickstart`.

Prerequisites
-------------

* Python ≥ 3.10 (a virtual environment with ``aiohttp`` is recommended)
* ``tmux``, ``git``, and the ``claude`` CLI (Claude Code)
* A QQ bot registered on the QQ Open Platform, with ``APP_ID`` and
  ``CLIENT_SECRET`` credentials

Environment variables
---------------------

The bridge reads its configuration from a ``.env`` file. The first existing
file wins, in this order:

1. ``.env`` in the current working directory
2. ``packages/claude-code-qq-bridge/.env``
3. ``~/agent-keep/.env``

Required keys:

.. code-block:: ini

   APP_ID=YOUR_QQ_BOT_APP_ID
   CLIENT_SECRET=YOUR_QQ_BOT_CLIENT_SECRET
   # Master user OpenID (leave empty to auto-bind the first user who sends a message)
   MASTER_OPENID=
   # Bound tmux session number (default: 1)
   TMUX_SESSION=1

Start the bridge
----------------

The recommended way is to manage the bridge with ``start.sh`` (logs are
collected in ``~/agent-keep/logs/bridge.log``):

.. code-block:: bash

   # Start
   ./start.sh start

   # Show status
   ./start.sh status

   # Restart
   ./start.sh restart

   # Stop
   ./start.sh stop

``start.sh`` runs the bridge in the background and records its PID in
``logs/bridge.pid``.

Logs
----

All logs are written to ``~/agent-keep/logs/bridge.log``:

.. code-block:: bash

   tail -f ~/agent-keep/logs/bridge.log

Run manually (debugging)
------------------------

.. code-block:: bash

   cd ~/agent-keep/packages/claude-code-qq-bridge
   pip install -e .
   claude-code-qq-bridge

Or without installing:

.. code-block:: bash

   python3 -c "import sys; sys.path.insert(0, 'packages/claude-code-qq-bridge/src'); from claude_code_qq_bridge.bridge import cli; import sys; sys.exit(cli())"

Verification
------------

* ``./start.sh status`` prints ``Bridge running: pid N``;
* send a plain message to the bot from QQ on your phone — you should receive
  a reply from Claude;
* ``tail -f ~/agent-keep/logs/bridge.log`` shows lines such as ``[Recv]`` and
  ``[QQ -> Claude]``.
