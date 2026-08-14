QQ 命令参考
===========

命令都在 `handle_c2c_message()` 中分发。下表为当前代码支持的完整命令列表，
按字母序；别名并列给出。

命令总览
--------

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - 命令
     - 别名
     - 作用
   * - ``/stop``
     - ``/tingzhi`` ``/kill``
     - 中断当前任务
   * - ``/resume``
     - ``/huifu`` ``/history``
     - 列出历史会话；``/resume N`` 恢复指定会话
   * - ``/cd <path>``
     -
     - 切换 Claude 的工作目录
   * - ``/sendimg <path>``
     -
     - 发送 Bridge 主机上的本地图片
   * - ``/sendfile <path>``
     -
     - 发送 Bridge 主机上的本地文件
   * - ``/mode``
     -
     - 切换权限模式；``/mode status`` 查看当前模式
   * - ``/context``
     -
     - 显示当前上下文用量
   * - ``/compact``
     -
     - 压缩当前对话
   * - ``/clear``
     - ``/new`` ``/reset`` ``/qingkong`` ``/xin duihua``
     - 开启新会话
   * - ``/btw <问题>``
     - ``/by-the-way``
     - 问一个"顺便问一下"的问题（本地面板回答，不打断主流程）
   * - ``/pwd``
     -
     - 显示当前工作目录
   * - ``/ls [path]``
     -
     - 列出目录内容（最多显示 50 项）

命令详解
--------

``/stop``（别名 ``/tingzhi`` / ``/kill``）
    **用途**：中断 Claude 当前正在进行的任务。
    **参数**：无。
    **示例**：``/stop``
    **注意**：由 Bridge 直接处理，不经过 Claude，也不会杀掉 Claude 进程本身——
    Claude 保持存活，只是当前生成被中断。回复 ``⛔ Interrupted.``。

``/resume``（别名 ``/huifu`` / ``/history``）
    **用途**：列出当前项目的历史会话；``/resume N`` 恢复其中第 N 个。
    **参数**：无参数 = 列出最近 10 个会话（带编号、时间、大小、token、标题）；
    一个数字 = 恢复对应编号的会话。
    **示例**：``/resume`` 显示会话列表；``/resume 1`` 恢复列表中第 1 个会话。

    **注意**：恢复前会先从目标会话的 JSONL 解析真实 ``cwd``，解析不到会**中止恢复**
    （避免在错误目录启动）。恢复过程持 ``_cmd_lock``。

``/cd <path>``
    **用途**：切换 Claude 的工作目录。
    **参数**：一个绝对路径。
    **示例**：``/cd /home/xuyang/projects/webapp``
    **注意**：由 Bridge 本地处理（持锁），不经过 Claude。

``/sendimg <path>``
    **用途**：把 Bridge 主机上的图片发给 Claude。
    **参数**：主机上的图片绝对路径（jpg / jpeg / png / webp，≤10MB）。
    **示例**：``/sendimg /home/xuyang/screenshots/shot.png``

``/sendfile <path>``
    **用途**：把 Bridge 主机上的文件发给 Claude。
    **参数**：主机上的文件绝对路径（pdf / docx / xlsx / pptx / txt / zip 等）。
    **示例**：``/sendfile /home/xuyang/reports/report.pdf``

``/mode``
    **用途**：切换 Claude 权限模式；``/mode status`` 只查询不切换。
    **参数**：无参数 = 按 ``Auto → Accept edits → Plan → Manual`` 循环切换；
    ``status`` = 查询当前模式。
    **示例**：``/mode`` 切换到下一模式；``/mode status`` 显示当前模式及来源
    （Claude session / bridge tracking / capture-pane）。

    **注意**：切换实际通过向 tmux 发送 ``BTab`` 完成，随后会尽力 capture-pane 验证。

``/context``
    **用途**：查看当前上下文用量（token 数）。
    **参数**：无。
    **注意**：向 Claude 发送 ``/context`` TUI 命令并解析输出。

``/compact``
    **用途**：压缩当前对话以节省 token。
    **参数**：无。
    **注意**：向 Claude 发送 ``/compact``。

``/clear``（别名 ``/new`` / ``/reset`` / ``/qingkong`` / ``/xin duihua``）
    **用途**：开启全新会话。
    **参数**：无。

``/btw <问题>``（别名 ``/by-the-way``）
    **用途**：问一个与主任务无关的"顺便问一下"的问题，答案由 Claude 在本地面板
    给出，不打断主流程。
    **参数**：问题文本。
    **示例**：``/btw 今天北京天气怎么样``

``/pwd``
    **用途**：显示 Claude 当前工作目录。
    **参数**：无。

``/ls [path]``
    **用途**：列出目录内容，本地处理，不经过 Claude。
    **参数**：可选路径；缺省为当前工作目录。
    **示例**：``/ls``、``/ls /etc``
    **注意**：隐藏文件不显示；最多显示 50 项，超出提示剩余数量。

审批按钮（``approve:``）
    Claude 请求审批时 QQ 会收到按钮。点击后 Bridge 把对应按键发送给 tmux：
    ``allow`` = 1、``allow_always`` = 2、``deny`` = 3。
    **注意**：只有当 Claude 确实存活在 pane 中时才会发送按键，避免误发到 Bash。
