# Changelog

本文件由 `scripts/release.py` 维护：每次正式发布时，把 `[Unreleased]` 下的条目转为对应版本号，并追加新版本。

格式约定：

- 每个版本一个 `## [x.y.z] - YYYY-MM-DD` 小节；
- 每个小节使用 `### Added / Changed / Fixed / Removed` 分类；
- `## [Unreleased]` 永远位于文件顶部，记录尚未发布的修改。

## [Unreleased]

## [0.1.0] - 2026-08-14

首个正式本地版本。本次把 QQ Bridge 从"能跑"变成"稳定可恢复"：

### Fixed

- 修复 `/resume` 后 PID=None，导致无法绑定会话
- 修复 PID / session 绑定错误
- 修复普通消息、`/btw` 面板内容误发送到 Bash 进程
- 修复 `/stop` 后 Claude 状态异常

### Added

- Claude 异常退出后自动 `--resume` 恢复
- Bridge 只绑定自己 tmux pane 内的 Claude（pane-scoped PID detection）
- 自动恢复后的 PID 重新绑定
- 统一日志到 `~/agent-keep/logs/bridge.log`
- 新增 `~/agent-keep/start.sh`（start / stop / restart / status）

### Changed

- 日志统一写入 `logs/bridge.log`，不再混入 `nohup.out`
- 会话恢复逻辑改为基于自身 tmux pane 检测，避免误绑定其他 Claude
