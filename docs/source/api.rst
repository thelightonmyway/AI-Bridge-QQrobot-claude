Python API
==========

本节由 ``sphinx.ext.autodoc`` 与 ``sphinx.ext.autosummary`` 从代码 docstring 自动生成，
函数签名、参数说明均来自源码，不会与代码脱节。构建文档时请先确认
:doc:`installation` 中提到的 Python 环境可用。

CLI 入口
--------

.. autosummary::
   :toctree: generated
   :nosignatures:

   claude_code_qq_bridge.bridge.cli

会话管理（同步）
----------------

.. autosummary::
   :toctree: generated
   :nosignatures:

   claude_code_qq_bridge.bridge.find_current_session
   claude_code_qq_bridge.bridge.refresh_session
   claude_code_qq_bridge.bridge.maybe_refresh_session
   claude_code_qq_bridge.bridge.get_session_status
   claude_code_qq_bridge.bridge.list_recent_sessions
   claude_code_qq_bridge.bridge.find_jsonl_path
   claude_code_qq_bridge.bridge.extract_cwd_from_jsonl
   claude_code_qq_bridge.bridge.project_name_to_cwd

核心操作（async）
-----------------

.. autosummary::
   :toctree: generated
   :nosignatures:

   claude_code_qq_bridge.bridge.send_to_claude
   claude_code_qq_bridge.bridge.start_claude_in_tmux
   claude_code_qq_bridge.bridge.stop_claude_in_tmux
   claude_code_qq_bridge.bridge.restart_claude_in_tmux
   claude_code_qq_bridge.bridge.get_tmux_pane_cwd
   claude_code_qq_bridge.bridge.capture_pane_stable

QQ 开放平台 API（async）
------------------------

.. autosummary::
   :toctree: generated
   :nosignatures:

   claude_code_qq_bridge.bridge.ensure_token
   claude_code_qq_bridge.bridge.get_gateway_url
   claude_code_qq_bridge.bridge.send_identify
   claude_code_qq_bridge.bridge.send_resume
   claude_code_qq_bridge.bridge.send_input_notify
   claude_code_qq_bridge.bridge.send_message_rest
   claude_code_qq_bridge.bridge.send_local_image
   claude_code_qq_bridge.bridge.send_local_file

事件处理与主循环（async）
-------------------------

.. autosummary::
   :toctree: generated
   :nosignatures:

   claude_code_qq_bridge.bridge.handle_c2c_message
   claude_code_qq_bridge.bridge.handle_interaction
   claude_code_qq_bridge.bridge.periodic_poll
   claude_code_qq_bridge.bridge.event_loop
   claude_code_qq_bridge.bridge.main

工具函数
--------

.. autosummary::
   :toctree: generated
   :nosignatures:

   claude_code_qq_bridge.bridge.load_env
   claude_code_qq_bridge.bridge.path_to_claude_project
   claude_code_qq_bridge.bridge.strip_ansi
   claude_code_qq_bridge.bridge.build_approval_keyboard
   claude_code_qq_bridge.bridge.get_http_client
   claude_code_qq_bridge.bridge.is_duplicate
   claude_code_qq_bridge.bridge.find_actions
