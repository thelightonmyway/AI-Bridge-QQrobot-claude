架构
====

数据流
------

::

    QQ 用户 ──> QQ 机器人 WebSocket ──> bridge ──> tmux send-keys ──> Claude Code
       ▲                                                          │
       └────────── QQ 消息 / 审批按钮 ◄──────── 捕获回复 ◄─────────┘

Claude Code 的输入输出都是交互式终端，Bridge 通过两个**独立通道**与它协作：

1. **session 文件通道**：读取 Claude 的 session 状态（如 ``waitingFor``），
   据此渲染 QQ 上的审批按钮；
2. **JSONL 通道**：读取 Claude 的对话 JSONL，把 assistant 文本作为回复推给 QQ。

QQ 按钮点击后，Bridge 再通过 ``tmux send-keys`` 把对应按键（如审批的 1/2/3、
``/mode`` 的 ``BTab``）发给 Claude，让任务继续。

设计原则
--------

bridge.py 头部声明的原则：

* **单会话保活**：同一时间只维护一个活跃 Claude 会话；
* **只读固定结构字段，不做内容分析**：Bridge 只解析 session/JSONL 的固定字段，
  不分析对话内容；
* **双通道独立**：session 状态与 JSONL 互不依赖；
* **缓存只用于重启检测**：不维护状态机；
* **不支持群消息** （只处理 C2C 单聊）；
* **无 Future / 状态机**。

模块划分
--------

``packages/claude-code-qq-bridge/`` 下：

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 文件
     - 作用
   * - ``src/claude_code_qq_bridge/bridge.py``
     - 主程序：QQ WebSocket、tmux 驱动、会话恢复、命令分发、媒体发送、审批按钮。
       约 2500 行，入口为 :func:`~claude_code_qq_bridge.bridge.cli`。
   * - ``claude-conversation-monitor.py``
     - 独立会话监控脚本：轮询 Claude JSONL，把对话写入 shell-snapshots 日志。
   * - ``claude-code-qq-bridge.py``
     - 顶层 standalone 入口（与包入口等价）。
   * - ``start.sh`` （仓库根目录）
     - Bridge 生命周期管理：start / stop / restart / status，日志统一到
       ``~/agent-keep/logs/bridge.log``。

会话恢复机制（v0.1.0 核心）
--------------------------------

* **pane-scoped PID detection**：Bridge 通过 tmux 找到**自己所在 pane** 内的 Claude
  进程，而不是全局匹配 ``claude``，避免误绑定其它终端里的 Claude；
* **自动 ``--resume``**：Claude 异常退出后，Bridge 自动用 ``--resume <session>``
  重启并重新绑定恢复后的 PID；
* **防误发**：``/btw`` 面板、普通消息在 Claude 未存活时**不会**被发送到 Bash
  （``_pane_has_claude()`` 守卫 + ``/resume N`` 前校验目标 cwd）。

QQ 侧
-----

* 通过 ``bots.qq.com`` 的 ``getAppAccessToken`` 换取 token（缓存并在过期前刷新）；
* 通过 gateway 建立 WebSocket，包含心跳、断线重连（2s→60s 退避）；
* 消息与事件经 ``handle_c2c_message`` / ``handle_interaction`` 分发；
* 图片 / 文件先上传 QQ 换取 URL，再以富媒体消息发送。

部署拓扑
--------

::

    ~/agent-keep/
    ├── .env                  # APP_ID / CLIENT_SECRET / MASTER_OPENID / TMUX_SESSION（不入库）
    ├── start.sh              # start / stop / restart / status
    ├── setup.sh              # 一键部署脚本（见 Quick Start）
    ├── logs/bridge.log       # 统一日志
    └── packages/claude-code-qq-bridge/   # 核心包
