Quick Start
===========

This guide takes you from a fresh machine to chatting with Claude Code from
QQ on your phone. The one-click setup script does the heavy lifting — all you
need to do is run it and fill in two credentials.

Step 1 — Prerequisites
----------------------

You need a machine with the following installed:

* ``python3`` and ``pip``
* ``tmux``
* ``git``
* the ``claude`` CLI (Claude Code)

.. code-block:: bash

   sudo apt install -y python3 python3-pip tmux git
   npm install -g @anthropic-ai/claude-code

You also need a QQ bot on the QQ Open Platform (https://q.qq.com), together
with its ``APP_ID`` and ``CLIENT_SECRET`` credentials.

Step 2 — Clone Agent Keep
-------------------------

.. code-block:: bash

   git clone https://github.com/thelightonmyway/agent-keep.git ~/agent-keep
   cd ~/agent-keep

Step 3 — Run the setup script
-----------------------------

Run the one-click setup script:

.. code-block:: bash

   ./setup.sh

The script automatically:

* checks that all dependencies are installed;
* detects your ``HOME`` and Claude projects directory;
* fetches the latest code (``git pull`` if ``~/agent-keep`` already exists);
* patches hard-coded paths in the source to match your user;
* installs the ``claude-code-qq-bridge`` package;
* creates a ``~/agent-keep/.env`` configuration template.

Step 4 — Fill in your credentials
---------------------------------

Edit ``~/agent-keep/.env`` and set your QQ bot credentials — the one step the
script cannot do for you:

.. code-block:: ini

   APP_ID=YOUR_QQ_BOT_APP_ID
   CLIENT_SECRET=YOUR_QQ_BOT_CLIENT_SECRET

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
