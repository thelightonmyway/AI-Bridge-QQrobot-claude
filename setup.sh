#!/usr/bin/env bash
# =============================================================================
# Claude Code QQ Bridge — 一键部署脚本
# =============================================================================
# 用途：把 QQ 机器人接入 Claude Code，让你用手机 QQ 直接调用 Claude
#
# 原理：QQ → QQ Bot WebSocket → agent-keep 桥接 → tmux → Claude Code
#
# 前置条件（请先完成）：
#   1. 去 https://q.qq.com 注册 QQ 机器人，得到 AppID 和 AppSecret
#   2. 确保已安装：python3, pip, tmux, git, claude
#
# 运行方式：
#   chmod +x setup.sh
#   ./setup.sh
# =============================================================================

set -euo pipefail

# ── 颜色输出 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── 标题 ────────────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   Claude Code QQ Bridge — 一键部署脚本       ║"
echo "  ║   让 QQ 成为 Claude Code 的远程键盘+显示器   ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── 1. 环境检查 ─────────────────────────────────────────────────────────────
info "检查环境依赖..."

MISSING=()

command -v python3 >/dev/null 2>&1 || MISSING+=("python3")
command -v pip     >/dev/null 2>&1 || MISSING+=("pip")
command -v tmux    >/dev/null 2>&1 || MISSING+=("tmux")
command -v git     >/dev/null 2>&1 || MISSING+=("git")
command -v claude  >/dev/null 2>&1 || MISSING+=("claude")

if [ ${#MISSING[@]} -gt 0 ]; then
    err "缺少依赖：${MISSING[*]}"
    echo "   请先安装：sudo apt install -y python3 python3-pip tmux git"
    exit 1
fi

ok "依赖检查通过"

# ── 2. 自动检测路径 ─────────────────────────────────────────────────────────
HOME_DIR="${HOME}"
CLAUDE_PROJECT="-$(echo "${HOME_DIR}" | sed 's|^/||' | tr '/' '-')"
AGENT_KEEP_DIR="${HOME_DIR}/agent-keep"

info "HOME         = ${HOME_DIR}"
info "Claude项目名  = ${CLAUDE_PROJECT}"

# 验证 Claude 项目目录存在
CLAUDE_PROJECTS="${HOME_DIR}/.claude/projects"
if [ ! -d "${CLAUDE_PROJECTS}" ]; then
    warn "未找到 ${CLAUDE_PROJECTS}，请先至少运行一次 claude"
fi

# ── 3. 克隆仓库 ─────────────────────────────────────────────────────────────
if [ -d "${AGENT_KEEP_DIR}/.git" ]; then
    info "agent-keep 已存在，拉取最新代码..."
    cd "${AGENT_KEEP_DIR}"
    git pull 2>/dev/null || warn "git pull 失败，使用现有代码"
else
    info "克隆 agent-keep..."
    if [ -d "${AGENT_KEEP_DIR}" ]; then
        warn "${AGENT_KEEP_DIR} 已存在但不是 git 仓库，备份后重新克隆..."
        mv "${AGENT_KEEP_DIR}" "${AGENT_KEEP_DIR}.bak.$(date +%s)"
    fi
    git clone https://github.com/zz327455573/agent-keep.git "${AGENT_KEEP_DIR}"
fi

ok "仓库就绪"

cd "${AGENT_KEEP_DIR}"

# ── 4. 修改源码，适配当前用户路径（原代码硬编码了 /root） ──────────────────
info "修补源码中的硬编码路径..."

BRIDGE_SRC_DIR="${AGENT_KEEP_DIR}/packages/claude-code-qq-bridge"
SRC_BRIDGE="${BRIDGE_SRC_DIR}/src/claude_code_qq_bridge/bridge.py"
TOP_BRIDGE="${BRIDGE_SRC_DIR}/claude-code-qq-bridge.py"
MONITOR="${BRIDGE_SRC_DIR}/claude-conversation-monitor.py"

# 备份文件，防止重复修补
patch_file() {
    local file="$1"
    if ! grep -q "CLAUDE_PROJECT = \"${CLAUDE_PROJECT}\"" "${file}" 2>/dev/null; then
        info "  修补: ${file}"

        # 1. CLAUDE_PROJECT
        sed -i "s|CLAUDE_PROJECT = \"-root\"|CLAUDE_PROJECT = \"${CLAUDE_PROJECT}\"|g" "${file}"

        # 2. cd /root → cd $HOME
        sed -i "s|cd /root &&|cd ${HOME_DIR} &&|g" "${file}"

        # 3. /root/claude-code-qq-bridge/.env → $HOME/agent-keep/.env
        sed -i "s|/root/claude-code-qq-bridge/.env|${HOME_DIR}/agent-keep/.env|g" "${file}"
    else
        info "  跳过（已修补）: ${file}"
    fi
}

# 修补主 bridge 源码
patch_file "${SRC_BRIDGE}"

# 额外处理 bridge.py：load_env 和 _save_master_openid 的 PermissionError 保护
if grep -q "Path.home() / \"agent-keep\" / \".env\"" "${SRC_BRIDGE}" 2>/dev/null; then
    info "  bridge.py PermissionError 保护已就绪"
else
    info "  添加 bridge.py PermissionError 保护..."

    # 用 Python 精确替换两个函数中的 .env 搜索路径和权限处理
    python3 << PYEOF
import re

with open("${SRC_BRIDGE}", "r") as f:
    content = f.read()

# 修补 load_env(): 替换 candidates 列表 + 添加 PermissionError 处理
old_load_env = '''    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path("/root/claude-code-qq-bridge/.env"),
    ]
    for p in candidates:
        if p.exists():
            try:'''

new_load_env = '''    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path.home() / "agent-keep" / ".env",
    ]
    for p in candidates:
        try:
            if not p.exists():
                continue
        except PermissionError:
            continue
        try:'''

content = content.replace(old_load_env, new_load_env)

# 修补 _save_master_openid(): 同样的修改（第二次出现）
# 找到第二次出现的位置，用计数方式
count = 0
def replace_second(match):
    global count
    count += 1
    if count == 2:
        return new_load_env.replace(
            'Path.home() / "agent-keep" / ".env"',
            'Path.home() / "agent-keep" / ".env"'
        )
    return match.group(0)

# 实际上第二次出现的结构略有不同（后面的代码块不同），手动处理
old_save = '''    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path("/root/claude-code-qq-bridge/.env"),
    ]
    for p in candidates:
        if p.exists():
            try:'''

# 在 _save_master_openid 函数中的第二次出现
# 找到 _save_master_openid 后的那个 candidates 块
parts = content.split('def _save_master_openid(')
if len(parts) == 2:
    before = parts[0]
    after_save = parts[1]
    # 替换函数内的 candidates 块
    after_save_replaced = after_save.replace(old_save, new_save := '''    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path.home() / "agent-keep" / ".env",
    ]
    for p in candidates:
        try:
            if not p.exists():
                continue
        except PermissionError:
            continue
        try:''')
    content = before + 'def _save_master_openid(' + after_save_replaced

with open("${SRC_BRIDGE}", "w") as f:
    f.write(content)

print("    bridge.py 保护已添加")
PYEOF
fi

# 修补顶级 standalone 文件（AGY 风格变体，可选）
if [ -f "${TOP_BRIDGE}" ]; then
    patch_file "${TOP_BRIDGE}"
fi

# 修补 conversation-monitor
if [ -f "${MONITOR}" ]; then
    if ! grep -q "${HOME_DIR}/.claude/projects/${CLAUDE_PROJECT}" "${MONITOR}" 2>/dev/null; then
        info "  修补: ${MONITOR}"
        sed -i "s|/root/.claude/projects/-root/|${HOME_DIR}/.claude/projects/${CLAUDE_PROJECT}/|g" "${MONITOR}"
        sed -i "s|/root/.claude/shell-snapshots/|${HOME_DIR}/.claude/shell-snapshots/|g" "${MONITOR}"
    else
        info "  跳过（已修补）: ${MONITOR}"
    fi
fi

ok "源码修补完成"

# ── 5. 安装 Python 包 ───────────────────────────────────────────────────────
info "安装 claude-code-qq-bridge..."
cd "${BRIDGE_SRC_DIR}"
pip install -e . --quiet 2>&1 | tail -1

# 验证安装
if command -v claude-code-qq-bridge >/dev/null 2>&1; then
    ok "claude-code-qq-bridge 安装成功: $(which claude-code-qq-bridge)"
else
    err "安装失败，请检查 pip 输出"
    exit 1
fi

cd "${AGENT_KEEP_DIR}"

# ── 6. 创建 .env 配置文件 ────────────────────────────────────────────────────
ENV_FILE="${AGENT_KEEP_DIR}/.env"

if [ -f "${ENV_FILE}" ] && grep -qv "YOUR_QQ_BOT" "${ENV_FILE}" 2>/dev/null; then
    info ".env 已配置，保留现有文件"
elif [ -f "${ENV_FILE}" ]; then
    info ".env 存在但未填写真实凭据，保留"
else
    info "创建 .env 配置模板..."
    cat > "${ENV_FILE}" << 'ENVEOF'
# ==========================================
# Claude Code QQ Bridge 配置文件
# ==========================================

# QQ Bot 官方平台 AppID 与 ClientSecret
APP_ID=YOUR_QQ_BOT_APP_ID
CLIENT_SECRET=YOUR_QQ_BOT_CLIENT_SECRET

# Master 用户的 OpenID（留空则自动绑定第一个发消息的用户）
MASTER_OPENID=

# 绑定的 tmux 会话号（默认为 1）
TMUX_SESSION=1
ENVEOF
    ok ".env 模板已创建"
fi

# ── 7. 最终验证 ─────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   ✅ 部署完成！                              ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
echo "  环境摘要："
echo "  ├─ HOME          : ${HOME_DIR}"
echo "  ├─ Claude 项目   : ${CLAUDE_PROJECT}"
echo "  ├─ bridge 命令   : $(which claude-code-qq-bridge)"
echo "  ├─ tmux 版本     : $(tmux -V)"
echo "  └─ claude 版本   : $(claude --version 2>&1 | head -1)"
echo ""
echo "  📋 接下来你需要做的："
echo ""
echo "  1. 编辑 .env 填入 QQ 机器人凭据："
echo "     nano ${AGENT_KEEP_DIR}/.env"
echo ""
echo "  2. 启动桥接（建议在 tmux 里运行）："
echo "     cd ${AGENT_KEEP_DIR}"
echo "     claude-code-qq-bridge"
echo ""
echo "  3. 如果想后台运行："
echo "     cd ${AGENT_KEEP_DIR} && nohup \$(which claude-code-qq-bridge) > /tmp/bridge.log 2>&1 &"
echo ""
echo "  4. 打开手机 QQ，给你的机器人发一条消息测试"
echo ""
echo "  📖 常用 QQ 指令："
echo "  ├─ 直接发消息  = 与 Claude 对话"
echo "  ├─ /new        = 开启新会话"
echo "  └─ /stop       = 中断当前任务"
echo ""

APP_ID_VALUE=$(grep "APP_ID=" "${ENV_FILE}" | cut -d= -f2)
if [ "${APP_ID_VALUE}" = "YOUR_QQ_BOT_APP_ID" ] || [ -z "${APP_ID_VALUE}" ]; then
    warn "⚠️  .env 中的 APP_ID 还未填写！编辑后即可启动"
fi
