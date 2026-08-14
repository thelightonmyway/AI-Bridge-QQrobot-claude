# agent-keep — 项目规则（Claude 必读）

本文件是本仓库对 Claude Code 的长期约定。当用户要求修改 `agent-keep` 时，必须遵守以下流程。

## 版本管理

- 单一版本号来源：仓库根目录 `VERSION` 文件（Sphinx 文档、release 脚本都从它取值）。
- 正式发布一律使用 `python3 scripts/release.py {patch|minor|major}`，不要手工改 VERSION / CHANGELOG / tag。
- 当前开发分支：`custom`（本地稳定版）。`master` 跟踪原作者 upstream，**不要向 origin push**。

## 修改 Keep 的标准流程

1. **修改前**先查看状态：

   ```bash
   git status
   git log --oneline -10
   git branch -vv
   ```

2. **不覆盖当前稳定版本**。稳定版本有 git tag（如 `v0.1.0`），随时可恢复。
3. 修改代码。
4. **做实际测试**（跑起来验证，不只看语法）。
5. 测试失败 → **不创建正式 release**。
6. 测试通过 → 向用户总结本轮修改。
7. 用户明确说"保存这一版"之后，才进行 release。
8. release 时：
   - 自动判断更合适的 `patch / minor / major`，给出建议；
   - 更新 CHANGELOG；
   - 更新版本号（VERSION）；
   - git commit；
   - git tag。
9. 每个版本必须可以通过 git 恢复（tag 即快照）。
10. **绝不提交**：API Key、QQ AppSecret、token、运行日志（`logs/`、`nohup.out`）、`.env`、`*.bak*`。它们都在 `.gitignore` 中。

## Release 后

- release 脚本**不会自动 push**。推送与否由用户决定。
- 推送目标不是 `origin`（原作者仓库）。若用户有自己的远端，用那个。

## 文档维护（控制 token 消耗）

- 版本更新记录优先基于 `git diff <last-tag>..HEAD` 与 `git log <last-tag>..HEAD` 生成，**不要重新通读整个项目**。
- API 文档由 Sphinx `autodoc` 从代码 docstring 自动生成，Claude 不手写全部 API 文档。
- Claude 只负责生成本次版本的人类可读 CHANGELOG 摘要。

## 本地预览文档

```bash
cd ~/agent-keep
python3 -m venv /tmp/docs-venv && /tmp/docs-venv/bin/pip install -r docs/requirements.txt
/tmp/docs-venv/bin/python3 -m sphinx -b html docs/source docs/_build/html
```

然后在浏览器打开 `docs/_build/html/index.html`。
