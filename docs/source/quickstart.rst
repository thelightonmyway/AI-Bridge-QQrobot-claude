Quick Start
===========

This guide takes you from a fresh machine to chatting with Claude Code from
QQ on your phone. The one-click setup script does the heavy lifting — all you
need to do is run it and fill in two credentials.

Step 1 — Prerequisites
----------------------

Make sure the following are in place:

* ``python3`` / ``pip``, ``tmux``, and ``git``
* Claude Code installed and working
* a QQ bot created on the QQ Open Platform, with its ``APP_ID`` and
  ``CLIENT_SECRET`` at hand

If Claude Code is missing, install it with the official native installer
(for Linux / WSL) and verify it:

.. code-block:: bash

   curl -fsSL https://claude.ai/install.sh | bash
   claude --version

Before continuing, configure Claude Code with an AI model provider of your
choice and make sure Claude Code can respond normally.

These are all the prerequisites — the setup script handles everything else.

Step 2 — Clone AI-Bridge-QQrobot-claude
---------------------------------------

.. code-block:: bash

   git clone https://github.com/thelightonmyway/AI-Bridge-QQrobot-claude.git
   cd AI-Bridge-QQrobot-claude

Step 3 — Run the setup script (pass your credentials)
-----------------------------------------------------

Run the one-click setup script with your QQ bot credentials:

.. code-block:: bash

   ./setup.sh <APP_ID> <CLIENT_SECRET>

The script automatically:

* checks that all dependencies are installed;
* detects your ``HOME`` and Claude projects directory;
* fetches the latest code (``git pull`` if ``~/AI-Bridge-QQrobot-claude`` already exists);
* installs the ``claude-code-qq-bridge`` package;
* writes your ``APP_ID`` / ``CLIENT_SECRET`` into ``~/AI-Bridge-QQrobot-claude/.env``.

If you prefer not to put credentials on the command line, run ``./setup.sh``
with no arguments — it creates a ``.env`` template you fill in by hand.

Step 4 — Optional: adjust configuration
---------------------------------------

Your credentials are already in ``~/AI-Bridge-QQrobot-claude/.env``. Open it
if you want to set optional values such as ``MASTER_OPENID`` (limit control to
one user) or ``TMUX_SESSION``:

.. code-block:: ini

   APP_ID=<your-app-id>
   CLIENT_SECRET=<your-client-secret>
   MASTER_OPENID=
   TMUX_SESSION=1

Step 5 — Start the bridge
-------------------------

.. code-block:: bash

   ./start.sh start
   ./start.sh status

``status`` should print ``Bridge running: pid N``.

Step 6 — Use it from QQ
-----------------------

Open QQ on your phone, find your bot, and send it a plain message. You will
get a reply from Claude. That is it.

For the full command list, see :doc:`commands`.

Updating
--------

``setup.sh`` installs a global command ``ai-bridge-update`` into
``~/.local/bin``. From **any directory**, update the project to the latest
version of the ``custom`` branch:

.. code-block:: bash

   ai-bridge-update

Update and then safely restart the QQ bridge (single instance only):

.. code-block:: bash

   ai-bridge-update --restart

The updater uses ``git fetch origin custom`` plus a **fast-forward only** merge —
it never runs ``git reset --hard``, so local edits to tracked files are never
silently overwritten. If any tracked file has local modifications, the update
stops and lists those files. Your ``.env`` is ignored by git and its content is
verified unchanged before and after every update; the Python editable install of
``claude-code-qq-bridge`` is refreshed and verified automatically.

Alternative, from the project directory:

.. code-block:: bash

   cd ~/AI-Bridge-QQrobot-claude
   ./update.sh            # update only
   ./update.sh --restart  # update + safe restart
