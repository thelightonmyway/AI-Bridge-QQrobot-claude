#!/usr/bin/env bash
# =============================================================================
# AI-Bridge-QQrobot-claude — 一键更新脚本（update.sh）
# =============================================================================
# 全局命令 ai-bridge-update 的全部逻辑都在本文件。
# ~/.local/bin/ai-bridge-update 只是一个稳定 launcher，调用本脚本并透传参数。
#
# 用法：
#   ./update.sh              # 只更新 + 验证，不重启 Bridge
#   ./update.sh --restart    # 更新完成后安全重启 QQ Bridge（保证单实例）
#   ./update.sh --help       # 显示帮助
#
# 更新策略：
#   git fetch origin custom
#   git merge --ff-only origin/custom      # 只允许快进合并
#   ---------- 绝不默认使用 git reset --hard ----------
#   若本地 tracked 文件有修改 → 停止更新并列出文件，绝不覆盖用户修改。
#
# 兼容性：可从任意目录调用；所有路径由 $HOME 动态推导，不写死用户名。
# 环境变量覆盖（便于测试 / 高级用法）：
#   AI_BRIDGE_REPO        项目目录（默认 $HOME/AI-Bridge-QQrobot-claude）
#   AI_BRIDGE_BRANCH      更新分支（默认 custom）
#   AI_BRIDGE_ORIGIN_URL  期望的 origin 地址（默认官方仓库）
#   BRIDGE_PYTHON         指定 Python 解释器（与 start.sh 共用）
# =============================================================================

set -uo pipefail

# ── 常量与默认值 ──────────────────────────────────────────────────────────────
REPO_DIR="${AI_BRIDGE_REPO:-${HOME}/AI-Bridge-QQrobot-claude}"
REMOTE_BRANCH="${AI_BRIDGE_BRANCH:-custom}"
EXPECTED_ORIGIN="${AI_BRIDGE_ORIGIN_URL:-https://github.com/thelightonmyway/AI-Bridge-QQrobot-claude.git}"

# ── 颜色输出（不依赖 tput，保持可移植） ──────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERR]${NC}   $*"; }

# ── 参数解析（只认 --restart / --help，其它参数报错） ────────────────────────
RESTART=0
usage() {
    cat <<'EOF'
用法:
  ai-bridge-update [选项]

选项:
  --restart    更新完成后安全重启 QQ Bridge（确保只有一个实例）
  --help       显示本帮助
EOF
}
for arg in "$@"; do
    case "${arg}" in
        --restart) RESTART=1 ;;
        -h|--help) usage; exit 0 ;;
        *) err "未知参数: ${arg}"; usage; exit 2 ;;
    esac
done

OLD_COMMIT=""
NEW_COMMIT=""

# 更新记录（追加到 logs/update.log，logs/ 已在 .gitignore 中）
log_record() {
    local logfile="${REPO_DIR}/logs/update.log"
    mkdir -p "$(dirname "${logfile}")" 2>/dev/null || true
    echo "$(date '+%F %T') branch=${REMOTE_BRANCH} OLD=${OLD_COMMIT:-?} NEW=${NEW_COMMIT:-?} restart=${RESTART}" >> "${logfile}" 2>/dev/null || true
}

# ── 阶段 1：检查项目目录 ──────────────────────────────────────────────────────
if ! command -v git >/dev/null 2>&1; then
    err "未找到 git，请先安装 git。"
    exit 1
fi

if [ ! -d "${REPO_DIR}/.git" ]; then
    if [ -d "${REPO_DIR}" ]; then
        err "${REPO_DIR} 存在但不是 git 仓库。"
        echo "  请备份数据后重新运行 setup.sh，或设置 AI_BRIDGE_REPO 指向项目路径。"
    else
        err "项目目录不存在: ${REPO_DIR}"
        echo "  请先运行 setup.sh 安装，或设置 AI_BRIDGE_REPO 指向项目路径。"
    fi
    exit 1
fi
info "项目目录 : ${REPO_DIR}"

# ── 阶段 2：检查 Git 仓库与 origin ────────────────────────────────────────────
if ! git -C "${REPO_DIR}" remote get-url origin >/dev/null 2>&1; then
    err "仓库没有配置 origin 远端。"
    echo "  建议: git -C ${REPO_DIR} remote add origin ${EXPECTED_ORIGIN}"
    exit 1
fi
ORIGIN_URL="$(git -C "${REPO_DIR}" remote get-url origin)"
info "origin    : ${ORIGIN_URL}"
if [ "${ORIGIN_URL}" != "${EXPECTED_ORIGIN}" ]; then
    err "origin 指向的仓库与官方仓库不一致："
    echo "    当前 origin : ${ORIGIN_URL}"
    echo "    预期        : ${EXPECTED_ORIGIN}"
    echo "  为安全起见已停止更新（避免从陌生远端拉取代码）。"
    echo "  若这是你的镜像/测试仓库，可设置 AI_BRIDGE_ORIGIN_URL 覆盖后重试。"
    exit 1
fi

cd "${REPO_DIR}"

# ── 阶段 3：.env 保护 — 更新前记录哈希并确认已被 .gitignore 覆盖 ────────────────
ENV_FILE="${REPO_DIR}/.env"
ENV_BEFORE=""
if [ -f "${ENV_FILE}" ]; then
    if git check-ignore -q .env 2>/dev/null; then
        ok ".env 已在 .gitignore 中（不会被提交/覆盖）"
    else
        warn ".env 不在 .gitignore 中！为避免凭据被提交，请手动加入。"
    fi
    ENV_BEFORE="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
else
    warn "未找到 .env（跳过内容校验）"
fi

# ── 阶段 4：拉取远端分支 ──────────────────────────────────────────────────────
info "拉取远端 ${REMOTE_BRANCH} 分支 (git fetch origin ${REMOTE_BRANCH})..."
if ! git fetch origin "${REMOTE_BRANCH}"; then
    if ! (exec 3<>/dev/tcp/github.com/443) 2>/dev/null; then
        err "无法连接 GitHub（网络不通），更新失败。"
    else
        err "git fetch 失败（网络异常或 GitHub 暂时不可用）。"
    fi
    echo "  可稍后重试: ai-bridge-update"
    exit 1
fi
ok "fetch 完成"

# ── 阶段 5：判断本地是否已是最新版 ─────────────────────────────────────────────
if ! git rev-parse --verify "origin/${REMOTE_BRANCH}" >/dev/null 2>&1; then
    err "远端不存在分支 origin/${REMOTE_BRANCH}，无法更新。"
    exit 1
fi
OLD_COMMIT="$(git rev-parse HEAD)"
NEW_COMMIT="$(git rev-parse "origin/${REMOTE_BRANCH}")"
BEHIND="$(git rev-list --count "HEAD..origin/${REMOTE_BRANCH}")"   # 远端有而本地没有
AHEAD="$(git rev-list --count "origin/${REMOTE_BRANCH}..HEAD")"   # 本地有而远端没有

if [ "${OLD_COMMIT}" = "${NEW_COMMIT}" ]; then
    ok "已是最新版本（${REMOTE_BRANCH}）: ${NEW_COMMIT:0:12}"
elif [ "${AHEAD}" -gt 0 ] && [ "${BEHIND}" -gt 0 ]; then
    err "本地分支与 origin/${REMOTE_BRANCH} 已分叉（本地 +${AHEAD} / 远端 +${BEHIND} 个提交）。"
    echo "  为避免丢失本地提交，请手动合并后再运行本命令："
    echo "    git -C ${REPO_DIR} merge origin/${REMOTE_BRANCH}"
    log_record
    exit 1
elif [ "${AHEAD}" -gt 0 ]; then
    # 仅本地领先（有未推送提交），远端没有新内容
    warn "本地领先远端 ${AHEAD} 个未推送提交，远端无新内容，无需更新。"
    warn "  如需发布本地提交，请自行 push 到 ${REMOTE_BRANCH}。"
elif [ "${BEHIND}" -gt 0 ]; then
    # 检查本地 tracked 文件是否有修改 —— 有修改则拒绝更新，绝不覆盖
    LOCAL_CHANGES="$(git status --porcelain | grep -vE '^\?\?' || true)"
    if [ -n "${LOCAL_CHANGES}" ]; then
        err "检测到本地 tracked 文件有修改，为避免覆盖你的修改，已停止更新："
        echo "${LOCAL_CHANGES}" | sed 's/^/    /'
        echo ""
        echo "  请先处理以上文件（提交或 stash），再重新运行: ai-bridge-update"
        log_record
        exit 1
    fi
    ok "工作区干净（tracked 文件无本地修改）"

    # 若当前不在目标分支则先切换
    CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
    if [ "${CURRENT_BRANCH}" != "${REMOTE_BRANCH}" ]; then
        info "当前分支 ${CURRENT_BRANCH}，切换到 ${REMOTE_BRANCH}..."
        if ! git checkout "${REMOTE_BRANCH}" 2>/dev/null; then
            err "无法切换到 ${REMOTE_BRANCH} 分支，已停止更新。"
            log_record
            exit 1
        fi
    fi

    info "发现新版本: ${OLD_COMMIT:0:12} -> ${NEW_COMMIT:0:12}"
    if ! git merge --ff-only "origin/${REMOTE_BRANCH}"; then
        err "快进合并失败（代码可能分叉，或本地存在冲突）。工作区未改变。"
        echo "  建议: 在 ${REPO_DIR} 下手动执行 git status 排查。"
        log_record
        exit 1
    fi
    ok "已快进到 ${REMOTE_BRANCH}@${NEW_COMMIT:0:12}"
else
    # 理论上不会走到这里（OLD != NEW 且 AHEAD/BEHIND 均为 0 的矛盾状态）
    err "无法判断更新状态，已停止。请手动检查: git -C ${REPO_DIR} status"
    log_record
    exit 1
fi

# ── 阶段 6：校验 .env 更新前后完全一致 ────────────────────────────────────────
if [ -n "${ENV_BEFORE}" ]; then
    ENV_AFTER="$(sha256sum "${ENV_FILE}" | awk '{print $1}')"
    if [ "${ENV_BEFORE}" = "${ENV_AFTER}" ]; then
        ok ".env 内容校验一致（更新前后未变化）"
    else
        err ".env 内容在更新过程中被改变！"
        echo "  请立即检查: ${ENV_FILE}"
        log_record
        exit 1
    fi
fi

# ── 阶段 7：刷新 Python editable install（复用 start.sh 的识别逻辑） ───────────
# 抽取自 start.sh 的共享实现，见 scripts/bridge-python.sh
if [ -f "${REPO_DIR}/scripts/bridge-python.sh" ]; then
    # shellcheck source=scripts/bridge-python.sh
    . "${REPO_DIR}/scripts/bridge-python.sh"
else
    # 极老版本兜底：用 PATH 上的 python3
    resolve_bridge_python() { echo "${BRIDGE_PYTHON:-$(command -v python3 || echo python3)}"; }
fi
PYTHON_BIN="$(resolve_bridge_python)"
info "使用 Python: ${PYTHON_BIN}"

PKG_DIR="${REPO_DIR}/packages/claude-code-qq-bridge"
if [ ! -d "${PKG_DIR}" ]; then
    err "未找到包目录: ${PKG_DIR}"
    echo "  当前已更新到 commit: ${NEW_COMMIT:0:12}（若本次有更新）"
    echo "  建议恢复: 重新运行 setup.sh，或手动:"
    echo "    git -C ${REPO_DIR} checkout ${REMOTE_BRANCH} -- packages/"
    log_record
    exit 1
fi

info "刷新 editable install: ${PKG_DIR}"
if ! (cd "${PKG_DIR}" && "${PYTHON_BIN}" -m pip install -e . --quiet); then
    err "Python editable install 失败。"
    echo ""
    echo "  代码已更新到 commit : ${NEW_COMMIT:0:12}（若本次有更新）"
    echo "  失败步骤           : pip install -e ${PKG_DIR}"
    echo "  建议恢复方法       : 手动执行以下命令后重试："
    echo "    cd ${PKG_DIR} && ${PYTHON_BIN} -m pip install -e ."
    echo "  或直接重跑安装    : ${REPO_DIR}/setup.sh"
    log_record
    exit 1
fi
ok "editable install 已刷新"

# ── 阶段 8：验证 bridge 可导入 / CLI 可用 ─────────────────────────────────────
VERIFY_OK=1
if ! "${PYTHON_BIN}" -c "import claude_code_qq_bridge" >/dev/null 2>&1; then
    VERIFY_OK=0
    warn "python -c \"import claude_code_qq_bridge\" 失败"
fi
CLI_PATH="$(dirname "${PYTHON_BIN}")/claude-code-qq-bridge"
if [ ! -x "${CLI_PATH}" ]; then
    VERIFY_OK=0
    warn "未找到 CLI: ${CLI_PATH}"
fi
if [ "${VERIFY_OK}" -eq 1 ]; then
    ok "验证通过: import 正常, CLI=${CLI_PATH}"
else
    err "安装验证失败（python 导入或 CLI 不可用）。"
    echo "  当前 commit: ${NEW_COMMIT:0:12}"
    echo "  建议恢复  : 重新运行 setup.sh，或手动:"
    echo "    cd ${PKG_DIR} && ${PYTHON_BIN} -m pip install -e ."
    log_record
    exit 1
fi

log_record

# ── 阶段 9：输出结果 ──────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   ✅ 更新完成                                ║"
echo "  ╚══════════════════════════════════════════════╝"
echo "  更新分支    : ${REMOTE_BRANCH}"
echo "  OLD_COMMIT  : ${OLD_COMMIT}"
echo "  NEW_COMMIT  : ${NEW_COMMIT}"
echo ""

# ── 阶段 10：--restart 安全重启 ───────────────────────────────────────────────
if [ "${RESTART}" -eq 1 ]; then
    restart_bridge() {
        local start_sh="${REPO_DIR}/start.sh"
        if [ ! -x "${start_sh}" ]; then
            err "未找到 start.sh，无法重启 Bridge。"
            return 1
        fi

        # 1. 判断 Bridge 是否正在运行
        local pid_file="${REPO_DIR}/logs/bridge.pid"
        local was_running=0
        if [ -f "${pid_file}" ] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
            was_running=1
            info "检测到 Bridge 正在运行 (pid $(cat "${pid_file}"))，先安全停止..."
            if ! "${start_sh}" stop; then
                err "停止旧 Bridge 失败。"
                return 1
            fi
            ok "旧 Bridge 已停止"
        else
            info "Bridge 当前未运行，将直接启动。"
        fi

        # 2. 启动 Bridge（start.sh 内部会写 pidfile）
        info "启动 Bridge..."
        if ! "${start_sh}" start; then
            err "启动 Bridge 失败，请查看 ${REPO_DIR}/logs/bridge.log"
            return 1
        fi

        # 3. 确认只存在一个 Bridge 实例
        # 用 [c]laude_code_qq_bridge 避免 pgrep -f 匹配到执行它的子 shell 自身
        # （子 shell 命令行里含该字符串会导致误报为 2 个进程）。
        sleep 1
        local running_count
        running_count="$(pgrep -f '[c]laude_code_qq_bridge' 2>/dev/null | wc -l | tr -d ' ')"
        if [ "${running_count}" -ne 1 ]; then
            err "检测到 ${running_count} 个 Bridge 相关进程（期望 1 个）。"
            echo "  请手动检查: pgrep -af '[c]laude_code_qq_bridge'"
            return 1
        fi

        # 4. 验证启动成功
        if [ -f "${pid_file}" ] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
            ok "Bridge 已重启，仅一个实例 (pid $(cat "${pid_file}"))"
            return 0
        else
            err "Bridge 启动验证失败（pidfile 无存活进程），请查看 ${REPO_DIR}/logs/bridge.log"
            return 1
        fi
    }

    if restart_bridge; then
        ok "更新 + 重启全部完成。"
    else
        err "Bridge 重启失败，但代码更新已完成。"
        echo "  当前 commit: ${NEW_COMMIT:0:12}"
        echo "  建议恢复  : ${REPO_DIR}/start.sh start"
        exit 1
    fi
else
    info "未指定 --restart，跳过重启。如需重启可运行: ai-bridge-update --restart"
fi

exit 0
