.. meta::
   :description: A persistent QQ bot bridge for Claude Code and other terminal CLI agents.

Agent Keep
==========

**Agent Keep** is a persistent CLI agent gateway monorepo. It connects
terminal-based agents — Claude Code, Codex, AGY, and similar — to QQ instant
messaging, so you can chat with Claude Code directly from QQ on your phone.

.. note::

   This documentation covers the **claude-code-qq-bridge** package, which
   connects Claude Code to QQ. The repository also contains two sibling
   packages, ``codex-qq-bridge`` and ``agy-qq-bridge``, with a similar
   structure.

Architecture at a glance
------------------------

.. code-block:: text

    Phone QQ ──> QQ bot WebSocket ──> bridge ──> tmux send-keys ──> Claude Code (interactive)
                                           ↑                             ↓
                                           └──── session / JSONL ────────→ replies pushed to QQ

A message sent from QQ is forwarded to Claude Code running inside a tmux
session. The reply is captured by the bridge and pushed back to QQ. If the
process crashes or exits unexpectedly, the bridge automatically resumes the
session with ``--resume`` and re-binds the new PID, so the conversation is
never lost.

Table of contents
-----------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   quickstart
   installation

.. toctree::
   :maxdepth: 2
   :caption: Usage

   usage
   commands
   architecture

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api
   changelog
   release

Version
-------

Current version: **v\ |version|**
