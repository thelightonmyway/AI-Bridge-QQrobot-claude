日常使用
========

对话
----

直接给机器人发普通消息，Bridge 会把消息转发给运行在 tmux 中的 Claude Code，并把回复推回 QQ。

普通消息、``/btw`` 面板内容等**不会**被误发送到 Bash —— 这是 v0.1.0 修复的防误发机制。

会话保持与自动恢复
------------------

* Bridge 只绑定**自己 tmux pane 内**的 Claude，不会误绑其它终端里的 Claude（pane-scoped PID detection）。
* 如果 Claude 异常退出，Bridge 会自动 ``--resume`` 恢复会话，并重新绑定恢复后的 PID。
* ``/resume`` 可手动列出历史会话并恢复指定会话（见 :doc:`commands`）。

权限模式
--------

Claude Code 的权限模式依次为 ``Auto`` → ``Accept edits`` → ``Plan`` → ``Manual``，
用 ``/mode`` 切换（等价于在 Claude 里按 ``Tab``），``/mode status`` 查看当前模式。

发送图片 / 文件
---------------

图片和文件来自 **Bridge 所在主机** 的路径，不是手机相册：

.. code-block:: text

   /sendimg /home/xuyang/screenshots/shot.png
   /sendfile /home/xuyang/reports/report.pdf

支持图片：jpg / jpeg / png / webp（≤10MB）；
支持文件：pdf / docx / xlsx / pptx / txt / zip 等。

会话管理
--------

* ``/clear`` 开启新会话；
* ``/compact`` 压缩当前对话以节省 token；
* ``/context`` 查看当前上下文用量。

多人使用
--------

若 ``MASTER_OPENID`` 为空，第一个发消息的用户会被自动绑定为 Master。
只有 Master 用户可以控制 Bridge。
