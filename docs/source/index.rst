Agent Keep
==========

**Agent Keep** 是一个持久的 CLI Agent 网关 monorepo：把 Claude Code / Codex / AGY 这些终端 CLI
Agent 接入 QQ 即时通讯，让你用手机 QQ 直接与 Claude Code 对话。

.. note::

   当前文档以 **claude-code-qq-bridge** （QQ Bridge）为核心，它也是本项目正在使用并持续维护的组件。
   仓库中还包含 codex-qq-bridge 与 agy-qq-bridge 两个兄弟包，结构类似，文档暂不逐一展开。

架构一句话
----------

::

    手机 QQ ──> QQ 机器人 WebSocket ──> bridge ──> tmux send-keys ──> Claude Code（交互模式）
                                          ↑                        ↓
                                          └──── session 文件 / JSONL ──→ push 回复给 QQ

QQ 发来消息 → Bridge 转发给运行在 tmux 里的 Claude Code → Claude 的回复被 Bridge 捕获 → 推回手机 QQ。
进程崩溃或异常退出时，Bridge 会自动 `--resume` 恢复会话并重新绑定 PID，保证"会话不丢"。

目录
----

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   quickstart
   installation

.. toctree::
   :maxdepth: 2
   :caption: 使用说明

   usage
   commands
   architecture

.. toctree::
   :maxdepth: 2
   :caption: 参考

   api
   changelog
   release

版本
----

当前版本：**v\ |version|**
