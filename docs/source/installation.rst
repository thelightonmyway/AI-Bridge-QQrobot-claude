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

Updating
--------

``setup.sh`` installs a global command ``ai-bridge-update`` into ``~/.local/bin``.
From **any directory**, update to the latest version of the ``custom`` branch:

.. code-block:: bash

   ai-bridge-update

Update and then safely restart the QQ bridge (single instance only):

.. code-block:: bash

   ai-bridge-update --restart

Both are thin wrappers around ``~/AI-Bridge-QQrobot-claude/update.sh`` (arguments
are passed through unchanged). The updater:

* checks the project directory, the ``origin`` remote, and network availability;
* refuses to proceed if any *tracked* file has local modifications — it lists the
  files instead of overwriting them (never ``git reset --hard``);
* fetches and fast-forwards with ``git merge --ff-only origin/custom``;
* protects ``.env`` — it is in ``.gitignore`` and its content hash is verified
  unchanged before and after the update;
* refreshes the Python editable install of ``claude-code-qq-bridge`` and verifies
  both ``import claude_code_qq_bridge`` and the ``claude-code-qq-bridge`` CLI;
* records the old/new commit in ``logs/update.log``.

Alternative, from the project directory:

.. code-block:: bash

   cd ~/AI-Bridge-QQrobot-claude
   ./update.sh            # update only
   ./update.sh --restart  # update + safe restart

Verify the setup
----------------

Send your bot a plain message from QQ. If you receive a reply from Claude,
everything is working. You can also confirm the process is alive:

.. code-block:: bash

   ./start.sh status
