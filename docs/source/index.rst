.. meta::
   :description: A persistent QQ bot bridge for Claude Code and other terminal CLI agents.

Agent Keep
==========

**Agent Keep** is a bridge between Claude Code and QQ. It lets you talk to
Claude Code directly from QQ on your phone, wherever you are.

.. note::

   **Acknowledgement**

   The initial development of Agent Keep was inspired in part by ideas and
   implementations from `zz327455573/agent-keep <https://github.com/zz327455573/agent-keep>`_.
   Many thanks to the original author for sharing their work and contributing
   to the community. Agent Keep is now maintained independently.

What can it do?
---------------

* **Chat with Claude Code from QQ** — send a message to your bot and get a
  reply from Claude, right in QQ on your phone.
* **Keep conversations alive** — if Claude exits or crashes, the bridge
  restores the session automatically.
* **Send images and files** from the bridge host to Claude.
* **Approve requests from QQ** — respond to Claude's permission prompts with
  a button tap.

How do I get started?
---------------------

The fastest way is the one-click setup script. It checks your dependencies,
fetches the code, installs the bridge, and prepares your configuration.

Ready to start? See :doc:`quickstart`.

Table of contents
-----------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   quickstart
   installation

.. toctree::
   :maxdepth: 2
   :caption: Using Agent Keep

   commands
   session-management
   usage

.. toctree::
   :maxdepth: 1
   :caption: Troubleshooting

   troubleshooting

.. toctree::
   :maxdepth: 1
   :caption: Reference

   changelog
