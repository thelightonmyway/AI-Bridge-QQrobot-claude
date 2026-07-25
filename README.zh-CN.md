# Agent Keep 🏠

> 让你的 CLI Agent 24 小时在线。手机随时遥控。

[![GitHub](https://img.shields.io/badge/Agent-Claude%20Code%20%7C%20Codex%20%7C%20AGY-blue)](https://github.com/zz327455573/agent-keep)
[![平台](https://img.shields.io/badge/平台-Linux%20%7C%20Windows-green)]()
[![通道](https://img.shields.io/badge/通道-QQ-orange)]()

[🇬🇧 English](README.md)

---

## 这是什么？

**不是又一个 IM 桥接器。这是一个持久化 Agent 网关。**

大部分"IM 接 AI"的项目是这样工作的：

```
用户发消息 → 启动一个进程 → 发送 prompt → 拿到回复 → 杀掉进程
```

**Agent Keep 不一样：**

```
Agent 常驻 tmux → 24 小时在线 → 手机发消息 →
Agent 做真实工作（文件、终端、浏览器、桌面）→ 
回复结果 → 上下文保持在线
```

**根本区别：**

| 普通 IM 桥 | Agent Keep |
|:--|:--|
| 每次请求新建 Agent 进程 | **Agent 在 tmux/ConPTY 里 24 小时常驻** |
| 桥负责维护聊天历史 | **Agent 自己管理会话，天然连续** |
| 只能调 API 有限的工具 | **完整的 CLI、终端、浏览器、桌面权限** |
| 长时间任务会超时 | **永远在线，无超时** |
| 一次只能跑一个 | **3 个以上 Agent 同时运行** |
| 不支持 Windows | **✅ Windows 桌面 API 直连** |

---

## 四个桥

每个桥都是独立可 pip 安装的包。你用哪个 Agent 就装哪个。

## 仓库结构

这个总仓现在已经包含真实源码，统一放在 [`packages/`](./packages) 目录下：

- `packages/claude-code-qq-bridge/`
- `packages/codex-qq-bridge/`
- `packages/agy-qq-bridge/`

顶层仓库是总 monorepo，每个桥子目录继续保留自己的 Python 包配置、命令入口和说明文档。

### 1. [Claude Code QQ 桥](https://github.com/zz327455573/claude-code-qq-bridge)
`claude-code-qq-bridge` — 最成熟的桥。
- ✅ QQ 卡片审批按钮
- ✅ Session 状态监控（`waitingFor` 检测）
- ✅ JSONL 增量日志读取（无 ANSI 乱码）
- ✅ 崩溃自动重启，单会话保活

### 2. [Codex QQ 桥](https://github.com/zz327455573/codex-qq-bridge)
`codex-qq-bridge` — 简洁干净，多轮对话。
- ✅ 多轮对话 + 会话续接
- ✅ 自适应 JSONL 文件绑定
- ✅ 不做审批拦截（Codex 原生处理）

### 3. [AGY QQ 桥 (Linux)](https://github.com/zz327455573/AGY-QQ-Bridge)
`agy-qq-bridge` — Google Antigravity 的异步日志监控桥。
- ✅ 纯异步，无忙锁
- ✅ 支持一次输入多次回复
- ✅ `/new` 后自适应绑定新日志文件

### 4. [AGY 反重力 QQ 桥 (Windows)](https://github.com/zz327455573/Antigravity-QQ-Bridge-Win)
`antigravity-qq-bridge-win` — Windows 桌面远程 AI 工作站。
- ✅ 直连 `language_server.exe` API（无需 PTY/ConPTY）
- ✅ 动态进程发现（自动检测端口 + CSRF token）
- ✅ 模型自动同步（读取桌面版 `settings.json`）
- ✅ 会话持久化（`conversation_id` 重启后仍保留）
- ✅ UTF-8 强制输出（emoji 不会导致 GBK 崩溃）

---

## 架构

```
┌──────────────────────────────────────────────────┐
│                    手机                            │
│              (QQ / 微信 / Telegram 等)              │
└──────────┬───────────────────────┬────────────────┘
           │                       │
           ▼                       ▼
┌──────────────────────────────────────────────────┐
│               Agent 网关（桥接层）                   │
│                                                    │
│  ┌──────────────┐    ┌──────────────┐              │
│  │  通道适配器   │    │ 通道适配器   │  ← 适配器模式 │
│  │  QQ (参考实现)│    │ 微信/飞书等  │               │
│  └──────┬───────┘    └──────┬───────┘              │
│         │                   │                       │
│         ▼                   ▼                       │
│  ┌────────────────────────────────────────┐        │
│  │            运行时层                      │        │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │        │
│  │  │ tmux │ │ConPTY│ │JSONL │ │Session│  │        │
│  │  │      │ │      │ │ 日志  │ │状态   │  │        │
│  │  └──┬───┘ └──┬───┘ └──┬───┘ └──┬────┘  │        │
│  └─────┼────────┼────────┼────────┼────────┘        │
└────────┼────────┼────────┼────────┼─────────────────┘
         │        │        │        │
         ▼        ▼        ▼        ▼
┌──────────────────────────────────────────────────┐
│  Claude Code │ Codex │ AGY │ AGY (Windows)       │
│  (24小时在线) │ (在线) │ (在线) │ (在线)             │
└──────────────────────────────────────────────────┘
         │         │        │        │
         ▼         ▼        ▼        ▼
┌──────────────────────────────────────────────────┐
│              电脑环境                              │
│  (文件、终端、浏览器、桌面自动化)                    │
└──────────────────────────────────────────────────┘
```

### 核心设计：通道抽象

每个桥 = **通道适配器** + **Agent 适配器**：

```
┌─────────────────────────────┐
│          桥                  │
│  ┌───────────┐ ┌─────────┐  │
│  │ 通道适配器 │ │Agent适配│  │
│  │           │ │ 器      │  │
│  │ • QQ WS   │ │ • tmux  │  │
│  │ • 微信    │ │ • ConPTY│  │
│  │ • Telegram│ │ • PTY   │  │
│  │ • Discord │ │         │  │
│  └───────────┘ └─────────┘  │
└─────────────────────────────┘
```

**QQ 是参考实现。** 换微信、Telegram、Discord 只用换通道适配器——Agent 运行时、会话管理、输出捕获全部保持不变。

---

## 这有什么用？

### 个人使用
你在服务器上跑着 Claude Code / Codex / AGY。每次 SSH 上去、敲命令、等结果。手机上看不了进度，断开连接上下文就丢了。

**有了 Agent Keep：**
- 打开 QQ → 发"帮我检查服务器" → 搞定 → 回复回来
- 长时间任务？随时发消息，做完自动回
- 新建会话？发 `/new`，桥自动重连

### 团队使用
- 同一台机器上同时跑多个 Agent
- 每个 Agent 独立持久会话，互不干扰
- Windows 机器当远程 AI 工作站用（浏览器、桌面、文件操作）

### 开发者使用
- 完整的 CLI 工具权限——不受 API 沙箱限制
- Agent 可以装包、改文件、跑脚本、控制浏览器
- 真正的持久会话，不需要重建上下文窗口

---

## 快速开始

```bash
# 克隆总仓
git clone https://github.com/zz327455573/agent-keep.git
cd agent-keep

# 选一个桥，从 packages 里安装：
pip install ./packages/claude-code-qq-bridge

# 或安装其他桥：
pip install ./packages/codex-qq-bridge
pip install ./packages/agy-qq-bridge

# 初始化（只问 QQ 机器人凭证）
claude-code-qq-bridge --init

# 运行
claude-code-qq-bridge
```

详细说明在每个桥的 README 里。

---

## 对比：Agent Keep vs. 其他方案

### vs. 普通 IM 桥（resume/replay 模式）
大多数桥每次收到消息就启动一个新 CLI 进程，把历史对话喂进去，回复完就杀掉。这意味着：
- 每次请求都要重新加载完整上下文（慢、贵）
- Agent 没有持久状态
- 无法持续访问工具

### vs. API 方案（OpenAI API 等）
API 方案的 Agent 被沙箱限制——不能碰你的文件、不能跑本地脚本、不能控制浏览器。

### vs. SSH + tmux 手动操作
Agent Keep **就是** SSH + tmux，但自动化了。你不需要 SSH 上去、attach 会话、敲命令、看输出。桥帮你做完了所有事。

---

## 路线图

- [ ] **微信/企业微信** 通道适配器
- [ ] **Telegram** 通道适配器
- [ ] **飞书** 通道适配器
- [ ] **Discord** 通道适配器
- [ ] 统一 CLI：`agent-keep start claude`
- [ ] Web 控制面板：查看所有 Agent、会话日志
- [ ] 多用户支持
- [ ] Docker 部署

---

## 核心理念

CLI Agent 是我们拥有的最强大的 AI 工具。它们跑在我们的机器上，拥有所有权限，能做真正的工作。唯一缺少的是**持久化**——它们被锁在终端里，绑在 SSH 会话上。

**Agent Keep 解决了这个问题。** 它给你的 Agent 一个永久的家，它们在那里生活、工作、等待你的指令。从任何地方。从你的手机。

---

## 开源协议

MIT。每个桥独立 MIT 协议。

---

**作者 [@zz327455573](https://github.com/zz327455573)** — 竹山文达门窗 / 个人 AI Agent 在线化
