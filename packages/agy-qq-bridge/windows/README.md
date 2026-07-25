# AGY-QQ-Bridge-Windows: 极简 Windows 异步 C2C QQ 桥接器

本项目是 Google Antigravity (AGY) 在 Windows 原生环境下的 QQ 机器人通道桥接程序。

---

## 🌟 核心特性与架构

由于 Windows 系统不支持原生的 `tmux` 或后台 PTY 发送按键，本项目采用了全新的 **One-off 单次命令自举连接** 或 **ConPTY 虚拟终端保活** 机制：

*   **进程保活**：在后台拉起一个 Windows 伪终端（ConPTY），保持 `agy.cmd` 长时间处于开启交互状态。
*   **按键流输送**：通过 Windows 虚拟终端句柄直接物理模拟键盘输入（\r\n），解决了标准 I/O 管道导致的 CLI 交互闪退或死锁问题。
*   **解耦读取**：输出端通过增量读取 `transcript.jsonl` 日志文件并推送到 QQ 客户端，实现完美的异步消息收发。

---

## 🛠️ 安装与部署指南

### 1. 安装 Windows 环境依赖

在 Windows 控制台（PowerShell 或 CMD）中执行以下命令，安装桥接器所需的异步与虚拟终端依赖库：
```powershell
pip install pywinpty httpx aiohttp
```

### 2. 配置环境变量

在脚本同级目录下创建 `.env` 环境变量配置文件，填写你的 QQ 机器人参数：
```env
APP_ID=你的QQ机器人AppID
CLIENT_SECRET=你的QQ机器人密钥
MASTER_OPENID=你的管理员OpenID
BRAIN_DIR=C:\Users\Administrator\.gemini\antigravity-cli\brain
LOG_DIR=C:\Users\Administrator\.agy-qq-bridge
```

### 3. 后台自启守护

推荐在 Windows 上使用 `NSSM` 或 Windows 任务计划程序将 `agy_qq_bridge_win.py` 包装为标准的系统服务，实现开机自动静默后台启动。
