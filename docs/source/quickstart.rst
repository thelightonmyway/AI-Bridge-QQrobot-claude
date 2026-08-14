快速上手（Quick Start）
=======================

本页面向**第一次使用**的人：从一台新电脑开始，用手机 QQ 直接跟 Claude Code 对话。

整体流程只有 3 步：

.. code-block:: text

    安装并配置 Claude
            ↓
    创建 QQ 机器人
            ↓
    运行 setup.sh
            ↓
    QQ 直接使用 Claude

Step 1 — 安装并配置 Claude Code 与 AI 模型
---------------------------------------------

1. 安装 Claude Code CLI：

   .. code-block:: bash

      npm install -g @anthropic-ai/claude-code

   （具体安装方式以 Claude Code 官方文档为准。）

2. 配置一个可供 Claude Code 使用的 AI 模型服务，并把 API 信息配给 Claude Code。
   需要准备的信息通常包括：

   .. code-block:: text

      API Base URL
      API Key / Auth Token
      Model Name

   例如 Claude Code 常用的环境变量：

   .. code-block:: text

      ANTHROPIC_BASE_URL
      ANTHROPIC_AUTH_TOKEN
      ANTHROPIC_MODEL

   .. note::
      如何购买 / 获取某个 AI 模型服务的 Key 属于各家平台流程，本文暂不展开，
      请先自行准备一个支持 Claude Code / Anthropic API 兼容格式的 AI 模型服务，
      并取得对应的 API Key。

3. 验证 Claude Code 可正常运行：

   .. code-block:: bash

      claude

   如果能正常进入 Claude Code 并进行对话，再继续下一步。

Step 2 — 建立 QQ 机器人并获取凭证
------------------------------------

1. 到 QQ 开放平台（https://q.qq.com）创建你的 QQ 机器人；
2. 取得运行 Bridge 所需的认证信息，通常是：

   .. code-block:: text

      APP_ID
      CLIENT_SECRET

   .. note::
      QQ 开放平台的注册与机器人创建流程本文暂不展开。预留后续补充：
      如何创建 QQ 机器人 / 如何获取 AppID / 如何获取 AppSecret / 如何配置机器人权限。

.. warning::
   **AppSecret、API Key 等敏感信息绝不能上传到 GitHub，也不能写进公开文档。**
   它们只存在于本机 ``~/.env`` / ``~/agent-keep/.env`` （已被 .gitignore 排除）。

Step 3 — 运行一键部署脚本
----------------------------

当前仓库的一键部署脚本是 **setup.sh** （不需要参数，运行后手动填写 `.env` 即可）：

.. code-block:: bash

   chmod +x setup.sh
   ./setup.sh

脚本会自动完成（内容来自脚本真实代码）：

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - 步骤
     - 说明
   * - 1. 环境检查
     - 检查 ``python3`` / ``pip`` / ``tmux`` / ``git`` / ``claude`` 是否已安装
   * - 2. 路径检测
     - 自动识别 HOME 与 Claude 项目目录（``~/.claude/projects/...``）
   * - 3. 拉取代码
     - 若 ``~/agent-keep`` 已存在则 ``git pull``，否则克隆仓库
   * - 4. 修补硬编码路径
     - 把源码里的 ``/root`` 等硬编码路径替换成当前用户的 HOME（可重复执行，已修补则跳过）
   * - 5. 安装 Python 包
     - ``pip install -e .`` 安装 ``claude-code-qq-bridge`` 并验证 ``claude-code-qq-bridge`` 命令可用
   * - 6. 生成 ``.env`` 模板
     - 在 ``~/agent-keep/.env`` 生成配置模板（已有真实凭据则保留）
   * - 7. 最终验证
     - 输出环境摘要与下一步指引

脚本运行完成后，编辑 ``~/agent-keep/.env`` 填入你的真实凭证：:

    APP_ID=你的QQ机器人AppID
    CLIENT_SECRET=你的QQ机器人ClientSecret
    MASTER_OPENID=     # 留空则自动绑定第一个发消息的用户
    TMUX_SESSION=1

安装完成后的使用方法
--------------------

用统一管理脚本控制 Bridge（推荐）：

.. code-block:: bash

   # 启动
   ./start.sh start

   # 查看状态
   ./start.sh status

   # 重启
   ./start.sh restart

   # 停止
   ./start.sh stop

日志位置：

.. code-block:: bash

   tail -f ~/agent-keep/logs/bridge.log

然后打开手机 QQ，给机器人发一条消息 —— 你就能用 QQ 直接使用 Claude 了。

最终用户体验
------------

::

    手机 QQ
       ↓
    QQ 机器人
       ↓
    Agent Keep / QQ Bridge
       ↓
    Claude Code
       ↓
    AI 模型

普通用户无需手动修改 Python 文件、tmux 配置或内部路径。

常见问题
--------

**``command -v claude`` 找不到**
    Claude Code 未安装或不在 PATH。先完成 Step 1。

**脚本报缺依赖（python3 / pip / tmux / git）**
    .. code-block:: bash

       sudo apt install -y python3 python3-pip tmux git

**启动后 QQ 没反应**
    先看日志：

    .. code-block:: bash

       tail -f ~/agent-keep/logs/bridge.log

    确认 ``APP_ID`` / ``CLIENT_SECRET`` 是否填写正确、机器人是否已通过审核并开启 C2C 消息。

**"⚠️ 无法确定该会话的工作目录"**
    恢复某历史会话时找不到其工作目录，属保护性中止。发送 ``/resume`` 重新选择会话。
