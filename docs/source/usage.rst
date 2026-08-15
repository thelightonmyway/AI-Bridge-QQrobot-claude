Common Usage
============

Chatting
--------

Send the bot a normal message. The bridge forwards it to Claude Code and
pushes the reply back to QQ.

When a reply is too long to be delivered as a normal QQ message, the bridge
automatically sends the complete response as a TXT file instead of
truncating it — so long answers always arrive in full.

Sending images and files
------------------------

Images and files come from a path on the bridge host, not from your phone:

.. code-block:: text

   /sendimg /path/to/screenshot.png
   /sendfile /path/to/report.pdf

Supported images: jpg / jpeg / png / webp (≤10 MB).
Supported files: pdf / docx / xlsx / pptx / txt / zip, and similar.

Permission modes
----------------

Claude Code's permission modes cycle through Auto → Accept edits → Plan →
Manual. Switch with ``/mode`` (equivalent to pressing Tab in Claude); use
``/mode status`` to view the current mode.

Multiple users
--------------

If ``MASTER_OPENID`` is empty, the first user who sends a message is
automatically bound as the Master. Only the Master user can control the
bridge.
