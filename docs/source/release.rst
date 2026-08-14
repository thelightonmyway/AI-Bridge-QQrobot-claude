发布流程
========

从 v0.1.0 起，所有正式版本都由 :file:`scripts/release.py` 统一管理，
**不需要手工修改** 版本号 / CHANGELOG / tag / 文档版本。

单一版本号来源
--------------

仓库根目录的 :file:`VERSION` 文件是唯一版本号来源：:

    echo "0.1.0" > VERSION

以下位置都从它取值：

* Sphinx 文档（:file:`docs/source/conf.py` 读取 :file:`VERSION`）
* release 脚本（:file:`scripts/release.py` 读写 :file:`VERSION`）
* 文档顶部显示的版本号

执行发布
--------

.. code-block:: bash

   python3 scripts/release.py patch   # 0.1.0 → 0.1.1
   python3 scripts/release.py minor   # 0.1.1 → 0.2.0
   python3 scripts/release.py major   # 0.2.0 → 1.0.0

脚本会依次：

1. 检查 Git working tree 是否干净（有未提交修改则中止）；
2. 读取上一个 Git tag，得到从上一版本以来的 commit/diff；
3. 按 ``patch / minor / major`` 规则推进 :file:`VERSION`；
4. 把 :file:`CHANGELOG.md` 中 ``[Unreleased]`` 条目转成正式版本条目；
5. 运行测试（存在 ``pytest`` / 测试目录时）；
6. 本地构建一次 Sphinx 文档，确认无错误；
7. 创建 Git commit（含 VERSION / CHANGELOG / 文档改动）；
8. 打 Git tag（如 ``v0.1.1``）。

**脚本不会自动 push**。结束后会提示：

.. code-block:: text

   Release v0.1.1 ready.
   Push to remote?

只有在确认要发布后才手动 push。

版本号规则
----------

.. list-table::
   :header-rows: 1
   :widths: 15 25 60

   * - 命令
     - 示例
     - 何时使用
   * - ``patch``
     - ``0.1.0 → 0.1.1``
     - Bug 修复、小改动
   * - ``minor``
     - ``0.1.1 → 0.2.0``
     - 新增功能（向后兼容）
   * - ``major``
     - ``0.2.0 → 1.0.0``
     - 破坏性变更 / 里程碑

恢复上一个稳定版本
------------------

每个版本都有 Git tag，随时可回滚：

.. code-block:: bash

   git tag                        # 查看所有版本
   git checkout v0.1.0            # 检出上一个稳定版本（或 git switch -c hotfix v0.1.0）
