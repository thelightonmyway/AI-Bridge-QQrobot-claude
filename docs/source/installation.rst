安装与启动
==========

本节面向已经拿到仓库、想在本机运行 Bridge 的用户。从零开始的一键部署见
:doc:`quickstart`。

前置条件
--------

* Python ≥ 3.10（建议使用带 ``aiohttp`` 的虚拟环境）
* ``tmux`` 、``git`` 、``claude`` （Claude Code CLI）
* 一个已在 QQ 开放平台注册的 QQ 机器人，取得 ``APP_ID`` 与 ``CLIENT_SECRET``

环境变量
--------

Bridge 从 `.env` 读取配置。查找顺序（第一个存在的生效）：

1. 当前工作目录的 ``.env``
2. ``packages/claude-code-qq-bridge/.env``
3. ``~/agent-keep/.env``

必需的键：

.. code-block:: ini

   APP_ID=你的QQ机器人AppID
   CLIENT_SECRET=你的QQ机器人ClientSecret
   # Master 用户 OpenID（留空则自动绑定第一个发消息的用户）
   MASTER_OPENID=
   # 绑定的 tmux 会话号（默认 1）
   TMUX_SESSION=1

``.env`` 已在 ``.gitignore`` 中，永远不会进入版本库。

启动 Bridge
-----------

统一通过 ``start.sh`` 管理（推荐，日志统一到 ``~/agent-keep/logs/bridge.log``）：

.. code-block:: bash

   # 启动
   ./start.sh start

   # 查看状态
   ./start.sh status

   # 重启
   ./start.sh restart

   # 停止
   ./start.sh stop

``start.sh`` 会把 Bridge 放到后台，PID 记录在 ``logs/bridge.pid``。

日志
----

所有日志统一写入 ``~/agent-keep/logs/bridge.log``：

.. code-block:: bash

   tail -f ~/agent-keep/logs/bridge.log

手动运行（调试用）
------------------

.. code-block:: bash

   cd ~/agent-keep/packages/claude-code-qq-bridge
   pip install -e .
   claude-code-qq-bridge

或不用安装：

.. code-block:: bash

   python3 -c "import sys; sys.path.insert(0, 'packages/claude-code-qq-bridge/src'); from claude_code_qq_bridge.bridge import cli; import sys; sys.exit(cli())"

验证
----

* ``./start.sh status`` 显示 ``Bridge running: pid N``；
* 手机 QQ 给机器人发一条普通消息，应收到 Claude 的回复；
* ``tail -f ~/agent-keep/logs/bridge.log`` 能看到 `[Recv]` 与 `[QQ -> Claude]` 等日志行。
