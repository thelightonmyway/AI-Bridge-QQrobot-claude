#!/usr/bin/env bash
# =============================================================================
# Claude Code QQ Bridge — 一键部署脚本
# =============================================================================
# 用途：把 QQ 机器人接入 Claude Code，让你用手机 QQ 直接调用 Claude
#
# 原理：QQ → QQ Bot WebSocket → AI-Bridge-QQrobot-claude 桥接 → tmux → Claude Code
#
# 前置条件（请先完成）：
#   1. 去 https://q.qq.com 注册 QQ 机器人，得到 AppID 和 AppSecret
#   2. 确保已安装：python3, pip, tmux, git, claude
#
# 运行方式：
#   chmod +x setup.sh
#   ./setup.sh                          # 创建 .env 模板，再手动填凭据
#   ./setup.sh <APP_ID> <CLIENT_SECRET> # 直接写入 QQ 机器人凭据
#
# 安装完成后，从任意目录更新到最新版：
#   ai-bridge-update            # 只更新
#   ai-bridge-update --restart  # 更新后安全重启 QQ Bridge
#
# 本项目基于 zz327455573/agent-keep 重开发（致谢原作者，详见 README），
# 但作为独立维护版本发布，安装直接取自本仓库（thelightonmyway/AI-Bridge-QQrobot-claude）。
# 仓库内所有路径均从 $HOME 动态推导，与具体 Linux 用户名无关，无需任何修补。
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

# ── 2. 自动检测路径（与用户名无关，全部由 $HOME 推导） ──────────────────────
HOME_DIR="${HOME}"
CLAUDE_PROJECT="-$(echo "${HOME_DIR}" | sed 's|^/||' | tr '/' '-')"
REPO_DIR="${HOME_DIR}/AI-Bridge-QQrobot-claude"

info "HOME           = ${HOME_DIR}"
info "Claude项目名    = ${CLAUDE_PROJECT}"
info "安装目录        = ${REPO_DIR}"

# 验证 Claude 项目目录存在
CLAUDE_PROJECTS="${HOME_DIR}/.claude/projects"
if [ ! -d "${CLAUDE_PROJECTS}" ]; then
    warn "未找到 ${CLAUDE_PROJECTS}，请先至少运行一次 claude"
fi

# ── 3. 克隆仓库 ─────────────────────────────────────────────────────────────
# 直接安装当前维护版本（thelightonmyway/AI-Bridge-QQrobot-claude，默认分支 custom），
# 代码内所有路径均动态推导，无需任何 sed / python 修补。
if [ -d "${REPO_DIR}/.git" ]; then
    info "AI-Bridge-QQrobot-claude 已存在，拉取最新代码..."
    cd "${REPO_DIR}"
    git pull 2>/dev/null || warn "git pull 失败，使用现有代码"
else
    info "克隆 AI-Bridge-QQrobot-claude..."
    if [ -d "${REPO_DIR}" ]; then
        warn "${REPO_DIR} 已存在但不是 git 仓库，备份后重新克隆..."
        mv "${REPO_DIR}" "${REPO_DIR}.bak.$(date +%s)"
    fi
    git clone https://github.com/thelightonmyway/AI-Bridge-QQrobot-claude.git "${REPO_DIR}"
fi

ok "仓库就绪"

# ── 4. 安装 Python 包 ───────────────────────────────────────────────────────
info "安装 claude-code-qq-bridge..."
cd "${REPO_DIR}/packages/claude-code-qq-bridge"
# 用 PATH 上的同一个 python3（环境检查里保证存在），aiohttp 等依赖一并安装
if python3 -m pip install -e . --quiet 2>&1 | tail -1; then
    ok "pip 安装完成"
else
    err "pip 安装失败，请检查上方 pip 输出"
    exit 1
fi

# 验证安装：console script 可用，或 python3 可直接 import 包
if command -v claude-code-qq-bridge >/dev/null 2>&1; then
    ok "claude-code-qq-bridge 安装成功: $(command -v claude-code-qq-bridge)"
elif python3 -c "import claude_code_qq_bridge" >/dev/null 2>&1; then
    ok "claude-code-qq-bridge 安装成功（python3 可直接 import）"
else
    err "安装验证失败，请检查 pip 输出"
    exit 1
fi

cd "${REPO_DIR}"

# ── 5. 安装全局更新命令 ai-bridge-update（幂等，可重复执行） ─────────────────
# 真正的更新逻辑在 update.sh；这里只装一个稳定 launcher，原样透传参数。
info "安装全局更新命令 ai-bridge-update..."
LAUNCHER_DIR="${HOME_DIR}/.local/bin"
mkdir -p "${LAUNCHER_DIR}"

# 保证 update.sh 可执行（避免 git 未保留可执行位）
chmod +x "${REPO_DIR}/update.sh" 2>/dev/null || true

LAUNCHER="${LAUNCHER_DIR}/ai-bridge-update"
cat > "${LAUNCHER}" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
# AI-Bridge-QQrobot-claude 全局更新命令（由 setup.sh 自动生成，可安全刷新）。
# 只作为稳定入口，完整透传参数给 update.sh：
#   ai-bridge-update --restart  ->  $HOME/AI-Bridge-QQrobot-claude/update.sh --restart
exec "${HOME}/AI-Bridge-QQrobot-claude/update.sh" "$@"
LAUNCHER_EOF
chmod +x "${LAUNCHER}"
ok "已安装: ${LAUNCHER}"

# 若 ~/.local/bin 不在 bash/zsh 的 rc 文件中，则幂等追加 PATH（不产生重复）
ensure_in_path() {
    local rc_file="$1"
    [ -f "${rc_file}" ] || return 0
    if ! grep -qF 'PATH="$HOME/.local/bin:$PATH"' "${rc_file}" 2>/dev/null; then
        printf '\n# Add ~/.local/bin to PATH (for ai-bridge-update)\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "${rc_file}"
        ok "已将 ~/.local/bin 加入 ${rc_file} 的 PATH"
    fi
}
ensure_in_path "${HOME_DIR}/.bashrc"
ensure_in_path "${HOME_DIR}/.zshrc"

# ── 6. 创建 .env 配置文件 ────────────────────────────────────────────────────
ENV_FILE="${REPO_DIR}/.env"

# 无参数时的默认配置模板
create_env_template() {
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
}

if [ $# -ge 2 ]; then
    # ./setup.sh <APP_ID> <CLIENT_SECRET> 直接写入凭据
    info "写入 .env（来自命令行参数）..."
    cat > "${ENV_FILE}" << EOF
# ==========================================
# Claude Code QQ Bridge 配置文件
# ==========================================

# QQ Bot 官方平台 AppID 与 ClientSecret（由 setup.sh 参数写入）
APP_ID=${1}
CLIENT_SECRET=${2}

# Master 用户的 OpenID（留空则自动绑定第一个发消息的用户）
MASTER_OPENID=

# 绑定的 tmux 会话号（默认为 1）
TMUX_SESSION=1
EOF
    ok ".env 已写入凭据（APP_ID=${1}）"
elif [ $# -eq 1 ]; then
    warn "用法：./setup.sh <APP_ID> <CLIENT_SECRET>（需两个参数），改用模板流程。"
    create_env_template
elif [ -f "${ENV_FILE}" ] && ! grep -q "YOUR_QQ_BOT" "${ENV_FILE}" 2>/dev/null; then
    info ".env 已配置，保留现有文件"
elif [ -f "${ENV_FILE}" ]; then
    info ".env 存在但未填写真实凭据，保留"
else
    info "创建 .env 配置模板..."
    create_env_template
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
echo "  ├─ 安装目录      : ${REPO_DIR}"
echo "  ├─ bridge 命令   : $(command -v claude-code-qq-bridge 2>/dev/null || echo 'python3 可 import（用 start.sh 启动）')"
echo "  ├─ tmux 版本     : $(tmux -V)"
echo "  └─ claude 版本   : $(claude --version 2>&1 | head -1)"
echo ""
echo "  📋 接下来你需要做的："
echo ""
echo "  1. 如果还没配置 QQ 机器人凭据，编辑 .env："
echo "     nano ${REPO_DIR}/.env      # 或用 ./setup.sh <APP_ID> <CLIENT_SECRET> 重新写入"
echo ""
echo "  2. 启动桥接："
echo "     cd ${REPO_DIR} && ./start.sh start"
echo ""
echo "  3. 查看状态 / 停止："
echo "     ./start.sh status   # 查看运行状态"
echo "     ./start.sh stop     # 停止"
echo ""
echo "  4. 打开手机 QQ，给你的机器人发一条消息测试"
echo ""
echo "  📖 常用 QQ 指令："
echo "  ├─ 直接发消息  = 与 Claude 对话"
echo "  ├─ /resume     = 恢复最近会话"
echo "  ├─ /new        = 开启新会话"
echo "  └─ /stop       = 中断当前任务"
echo ""
echo "  ────────────────────────────────────────────────"
echo ""
echo "  安装完成。"
echo ""
echo "  以后更新到最新版："
echo "    ai-bridge-update"
echo ""
echo "  更新并重启 QQ Bridge："
echo "    ai-bridge-update --restart"
echo ""

APP_ID_VALUE=$(grep "APP_ID=" "${ENV_FILE}" | cut -d= -f2)
if [ "${APP_ID_VALUE}" = "YOUR_QQ_BOT_APP_ID" ] || [ -z "${APP_ID_VALUE}" ]; then
    warn "⚠️  .env 中的 APP_ID 还未填写！编辑后即可启动"
fi
