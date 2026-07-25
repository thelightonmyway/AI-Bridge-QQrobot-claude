# Codex QQ Bridge 🚀

[![Agent Keep](https://img.shields.io/badge/🏠_Agent_Keep-生态项目-blue)](https://github.com/zz327455573/agent-keep)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![QQ Bot](https://img.shields.io/badge/QQ-Bot%20API-red.svg)](https://bot.q.qq.com/)

**Codex QQ 桥接网关** — 通过 QQ 官方 WebSocket 网关直连 [Codex CLI](https://github.com/openai/codex)，支持多轮对话、会话续接。

---

## 🌟 核心架构与优势

```mermaid
graph TD
    User([QQ 用户]) <-->|C2C 私聊| Bridge[python codex-qq-bridge.py]
    
    subgraph 本地环境
        Bridge -->|1. tmux send-keys| Tmux(tmux session: codex)
        Tmux <-->|运行交互| Codex[Codex CLI]
        Codex -->|2. 输出记录| Log[(rollout-*.jsonl 结构化日志)]
        Log -.->|3. 增量常驻扫描| Bridge
    end
```

*   **输入输出完全解耦**：QQ 消息只管送入 tmux，后台协程只管监听日志并广播回传。无忙碌锁、无同步超时死锁。
*   **支持长时间任务**：Codex 执行长任务时分步骤汇报进度时，所有输出自动捕获回传 QQ，不丢失。
*   **自适应会话切换**：执行 `/new` 重置后，监听器自动绑定新生成的 JSONL 文件，杜绝历史消息重复刷屏。
*   **无审批按钮**：Codex 使用 `--ask-for-approval on-request` 模式自行判断是否需用户确认，桥接层不做审批拦截。

---

## 🛠️ 安装与运行

### 1. 安装

```bash
# 从 GitHub 安装
pip install git+https://github.com/zz327455573/codex-qq-bridge.git

# 验证安装
which codex-qq-bridge
```

### 2. 配置

```bash
# 交互式配置（首次使用）
codex-qq-bridge --init

# 或手动创建 .env
cp .env.example .env
```

编辑 `.env`：

```env
APP_ID=你的QQ机器人AppID
CLIENT_SECRET=你的QQ机器人密钥
MASTER_OPENID=你的OpenID
TMUX_SESSION=codex
```

### 3. 运行

```bash
# 前台运行
codex-qq-bridge

# PM2 保活
pm2 start $(which codex-qq-bridge) --name codex-qq-bridge
```

---

## ⚙️ 配置说明

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `APP_ID` | ✅ | — | QQ 开放平台应用 ID |
| `CLIENT_SECRET` | ✅ | — | QQ 开放平台应用密钥 |
| `MASTER_OPENID` | ❌ | 自动绑定 | 管理员 QQ OpenID，留空时第一个发消息的用户自动成为管理员 |
| `TMUX_SESSION` | ❌ | `codex` | tmux 会话名称，用于常驻运行 Codex |
| `CODEX_HOME` | ❌ | `~/.codex` | Codex 数据目录（含 `sessions/`） |

---

## 💬 命令列表

在 QQ 私聊中发送以下命令控制桥接器：

| 命令 | 功能 |
|------|------|
| `/new` / `/reset` / `/qingkong` | 重启 Codex，开始新会话 |
| `/stop` / `/kill` | 停止 Codex（Ctrl+C） |
| 普通文本 | 直接发送给 Codex 处理 |

---

## 🗂️ 项目结构

```
codex-qq-bridge/
├── src/
│   └── codex_qq_bridge/
│       ├── __init__.py
│       ├── __main__.py
│       └── bridge.py          # 主桥接逻辑
├── .env.example               # 环境变量配置模板
├── pyproject.toml             # pip 包配置
├── .gitignore                 # Git 忽略规则
├── LICENSE                    # MIT 许可证
├── README.md                  # 本文件
├── docs/                      # 技术文档
└── evidence/                  # 运行截图/证据
```

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

## 🔗 相关项目

- [claude-code-qq-bridge](https://github.com/zz327455573/claude-code-qq-bridge) — Claude Code QQ 桥接网关
- [AGY-QQ-Bridge](https://github.com/zz327455573/AGY-QQ-Bridge) — Google AGY QQ 桥接网关
