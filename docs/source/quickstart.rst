Quick Start
===========

This page is for **first-time users**: start from a new machine and chat with
Claude Code directly from QQ on your phone.

The whole flow takes only three steps:

.. code-block:: text

   Install and configure Claude
            ↓
   Create a QQ bot
            ↓
   Run setup.sh
            ↓
   Use Claude from QQ

Step 1 — Install and configure Claude Code and an AI model
----------------------------------------------------------

1. Install the Claude Code CLI:

   .. code-block:: bash

      npm install -g @anthropic-ai/claude-code

   (See the Claude Code documentation for other installation methods.)

2. Set up an AI model service that Claude Code can use and configure its API
   credentials for Claude Code. You will typically need:

   .. code-block:: text

      API Base URL
      API Key / Auth Token
      Model Name

   For example, the environment variables commonly used by Claude Code:

   .. code-block:: text

      ANTHROPIC_BASE_URL
      ANTHROPIC_AUTH_TOKEN
      ANTHROPIC_MODEL

   .. note::
      Preparing an API key for a given AI model service depends on the
      provider. Make sure you have a model service that is compatible with
      the Claude Code / Anthropic API format, and its API key, ready before
      continuing.

3. Verify that Claude Code runs correctly:

   .. code-block:: bash

      claude

   If you can enter Claude Code and hold a conversation, continue to the next
   step.

Step 2 — Create a QQ bot and obtain credentials
-----------------------------------------------

1. Create your QQ bot on the QQ Open Platform (https://q.qq.com).
2. Obtain the credentials the bridge needs to run, typically:

   .. code-block:: text

      APP_ID
      CLIENT_SECRET

Step 3 — Run the one-click setup script
---------------------------------------

The one-click setup script is **setup.sh**. It takes no arguments; after it
finishes, you fill in your ``.env`` manually:

.. code-block:: bash

   chmod +x setup.sh
   ./setup.sh

The script performs the following steps:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Step
     - Description
   * - 1. Environment check
     - Checks that ``python3`` / ``pip`` / ``tmux`` / ``git`` / ``claude`` are installed
   * - 2. Path detection
     - Detects ``HOME`` and the Claude projects directory (``~/.claude/projects/...``)
   * - 3. Fetch the code
     - Runs ``git pull`` if ``~/agent-keep`` already exists, otherwise clones the repository
   * - 4. Patch hard-coded paths
     - Replaces hard-coded paths such as ``/root`` in the source with the current user's ``HOME`` (idempotent; skips already-patched files)
   * - 5. Install the Python package
     - Installs ``claude-code-qq-bridge`` with ``pip install -e .`` and verifies that the ``claude-code-qq-bridge`` command is available
   * - 6. Generate the ``.env`` template
     - Creates a configuration template at ``~/agent-keep/.env`` (keeps existing credentials if present)
   * - 7. Final verification
     - Prints an environment summary and next steps

After the script finishes, edit ``~/agent-keep/.env`` and fill in your real
credentials:

.. code-block:: ini

   APP_ID=YOUR_QQ_BOT_APP_ID
   CLIENT_SECRET=YOUR_QQ_BOT_CLIENT_SECRET
   # Master user OpenID (leave empty to auto-bind the first user who sends a message)
   MASTER_OPENID=
   TMUX_SESSION=1

Using the bridge
----------------

Manage the bridge with the unified script (recommended):

.. code-block:: bash

   # Start
   ./start.sh start

   # Show status
   ./start.sh status

   # Restart
   ./start.sh restart

   # Stop
   ./start.sh stop

Logs are written to:

.. code-block:: bash

   tail -f ~/agent-keep/logs/bridge.log

Then open QQ on your phone and send the bot a message — you can use Claude
directly from QQ.

The end-user experience
-----------------------

.. code-block:: text

   Phone QQ
     ↓
   QQ bot
     ↓
   Agent Keep / QQ Bridge
     ↓
   Claude Code
     ↓
   AI model

End users do not need to edit Python files, tmux configuration, or internal
paths by hand.

Troubleshooting
---------------

**``command -v claude`` fails**
    Claude Code is not installed or not on ``PATH``. Complete Step 1 first.

**The script reports missing dependencies (python3 / pip / tmux / git)**
    .. code-block:: bash

       sudo apt install -y python3 python3-pip tmux git

**The bot does not respond after starting**
    Check the logs first:

    .. code-block:: bash

       tail -f ~/agent-keep/logs/bridge.log

    Make sure ``APP_ID`` and ``CLIENT_SECRET`` are correct, and that the bot
    has been approved and enabled for C2C messaging.

**Session recovery aborts with a working-directory warning**
    When resuming an old session, the bridge aborts recovery protectively if
    it cannot determine that session's working directory (to avoid starting
    in the wrong directory). Send ``/resume`` to choose the session again.
