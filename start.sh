#!/usr/bin/env bash
# Claude Code QQ Bridge 统一启动/停止脚本
#
# 日志统一到 ~/AI-Bridge-QQrobot-claude/logs/bridge.log：
#   - 程序内 logging -> FileHandler 直接写 bridge.log
#   - stdout/stderr 也一并重定向到 bridge.log（兜底捕获 print / traceback）
# 不再出现"程序以为写在 bridge.log，实际却在 nohup.out"的混乱。
set -u

REPO="${HOME}/AI-Bridge-QQrobot-claude"
LOG_DIR="${BRIDGE_LOG_DIR:-${HOME}/AI-Bridge-QQrobot-claude/logs}"
LOG_FILE="${LOG_DIR}/bridge.log"
PIDFILE="${LOG_DIR}/bridge.pid"

mkdir -p "${LOG_DIR}"

# 定位运行 bridge 的 Python 解释器（与具体用户名无关，任何 Linux 用户都能用）。
# 逻辑已抽取到 scripts/bridge-python.sh，与 update.sh 共用单一实现。
# shellcheck source=scripts/bridge-python.sh
. "${REPO}/scripts/bridge-python.sh"

PYTHON_BIN="$(resolve_bridge_python)"
if ! "${PYTHON_BIN}" -c "import aiohttp" >/dev/null 2>&1; then
    echo "WARN: 未找到带 aiohttp 的 Python。" >&2
    echo "      可设置 BRIDGE_PYTHON 指向正确的解释器，或确认依赖已安装（./setup.sh 会自动装）。" >&2
fi

# scripts/setup-codex.sh 成功后才会创建此 marker。没有 marker 时完全不触碰 CLIProxyAPI。
CLIPROXY_MARKER="${HOME}/.cli-proxy-api/ai-bridge-codex.env"
CLIPROXY_RUNTIME_BIN=""
CLIPROXY_RUNTIME_CONFIG=""
CLIPROXY_RUNTIME_HOST=""
CLIPROXY_RUNTIME_PORT=""
CLIPROXY_RUNTIME_PIDFILE=""
CLIPROXY_RUNTIME_LOG=""

load_cliproxy_runtime() {
    [ -f "${CLIPROXY_MARKER}" ] || return 1

    local AI_BRIDGE_CLIPROXY_BIN=""
    local AI_BRIDGE_CLIPROXY_CONFIG=""
    local AI_BRIDGE_CLIPROXY_HOST=""
    local AI_BRIDGE_CLIPROXY_PORT=""
    # marker 由 setup-codex.sh 生成，仅含 shell-escaped 的非敏感路径与 host/port。
    # shellcheck disable=SC1090
    . "${CLIPROXY_MARKER}"

    [ -n "${AI_BRIDGE_CLIPROXY_BIN}" ] || return 1
    [ -n "${AI_BRIDGE_CLIPROXY_CONFIG}" ] || return 1
    [ -n "${AI_BRIDGE_CLIPROXY_HOST}" ] || return 1
    [[ "${AI_BRIDGE_CLIPROXY_PORT}" =~ ^[0-9]+$ ]] || return 1

    CLIPROXY_RUNTIME_BIN="${AI_BRIDGE_CLIPROXY_BIN}"
    CLIPROXY_RUNTIME_CONFIG="${AI_BRIDGE_CLIPROXY_CONFIG}"
    CLIPROXY_RUNTIME_HOST="${AI_BRIDGE_CLIPROXY_HOST}"
    CLIPROXY_RUNTIME_PORT="${AI_BRIDGE_CLIPROXY_PORT}"
    CLIPROXY_RUNTIME_PIDFILE="$(dirname "${CLIPROXY_MARKER}")/server.pid"
    CLIPROXY_RUNTIME_LOG="$(dirname "${CLIPROXY_MARKER}")/logs/server.log"
}

cliproxy_socket_reachable() {
    "${PYTHON_BIN}" - "${CLIPROXY_RUNTIME_HOST}" "${CLIPROXY_RUNTIME_PORT}" <<'PY' >/dev/null 2>&1
import socket
import sys
try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=0.5):
        pass
except OSError:
    raise SystemExit(1)
PY
}

cliproxy_pid_running() {
    [ -f "${CLIPROXY_RUNTIME_PIDFILE}" ] || return 1
    local pid
    pid="$(cat "${CLIPROXY_RUNTIME_PIDFILE}" 2>/dev/null || true)"
    [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null
}

ensure_cliproxy_running() {
    [ -f "${CLIPROXY_MARKER}" ] || return 0
    if ! load_cliproxy_runtime; then
        echo "ERROR: Codex marker 无效: ${CLIPROXY_MARKER}" >&2
        return 1
    fi
    if cliproxy_socket_reachable; then
        return 0
    fi
    if cliproxy_pid_running; then
        echo "ERROR: CLIProxyAPI pid 存活但 ${CLIPROXY_RUNTIME_HOST}:${CLIPROXY_RUNTIME_PORT} 不可达" >&2
        return 1
    fi
    if [ ! -x "${CLIPROXY_RUNTIME_BIN}" ]; then
        echo "ERROR: CLIProxyAPI 不可执行: ${CLIPROXY_RUNTIME_BIN}" >&2
        return 1
    fi
    if [ ! -f "${CLIPROXY_RUNTIME_CONFIG}" ]; then
        echo "ERROR: CLIProxyAPI 配置不存在: ${CLIPROXY_RUNTIME_CONFIG}" >&2
        return 1
    fi

    mkdir -p "$(dirname "${CLIPROXY_RUNTIME_LOG}")"
    chmod 700 "$(dirname "${CLIPROXY_RUNTIME_LOG}")"
    touch "${CLIPROXY_RUNTIME_LOG}"
    chmod 600 "${CLIPROXY_RUNTIME_LOG}"
    echo "Starting CLIProxyAPI for Codex..."
    nohup "${CLIPROXY_RUNTIME_BIN}" -config "${CLIPROXY_RUNTIME_CONFIG}" \
        >> "${CLIPROXY_RUNTIME_LOG}" 2>&1 &
    local pid=$!
    printf '%s\n' "${pid}" > "${CLIPROXY_RUNTIME_PIDFILE}"
    chmod 600 "${CLIPROXY_RUNTIME_PIDFILE}"

    local i
    for i in $(seq 1 20); do
        if ! kill -0 "${pid}" 2>/dev/null; then
            rm -f "${CLIPROXY_RUNTIME_PIDFILE}"
            echo "ERROR: CLIProxyAPI exited immediately — see ${CLIPROXY_RUNTIME_LOG}" >&2
            return 1
        fi
        if cliproxy_socket_reachable; then
            echo "CLIProxyAPI ready: ${CLIPROXY_RUNTIME_HOST}:${CLIPROXY_RUNTIME_PORT}"
            return 0
        fi
        sleep 0.25
    done

    kill "${pid}" 2>/dev/null || true
    rm -f "${CLIPROXY_RUNTIME_PIDFILE}"
    echo "ERROR: CLIProxyAPI did not become ready — see ${CLIPROXY_RUNTIME_LOG}" >&2
    return 1
}

cliproxy_status() {
    [ -f "${CLIPROXY_MARKER}" ] || return 0
    if ! load_cliproxy_runtime; then
        echo "CLIProxyAPI configured but marker is invalid"
    elif cliproxy_socket_reachable && cliproxy_pid_running; then
        echo "CLIProxyAPI running: pid $(cat "${CLIPROXY_RUNTIME_PIDFILE}") (${CLIPROXY_RUNTIME_HOST}:${CLIPROXY_RUNTIME_PORT})"
    elif cliproxy_socket_reachable; then
        echo "CLIProxyAPI reachable: ${CLIPROXY_RUNTIME_HOST}:${CLIPROXY_RUNTIME_PORT} (external process)"
    elif cliproxy_pid_running; then
        echo "CLIProxyAPI unhealthy: pid $(cat "${CLIPROXY_RUNTIME_PIDFILE}") (${CLIPROXY_RUNTIME_HOST}:${CLIPROXY_RUNTIME_PORT} unreachable)"
    else
        echo "CLIProxyAPI not running (${CLIPROXY_RUNTIME_HOST}:${CLIPROXY_RUNTIME_PORT})"
    fi
}

# 用 python -c 注入 sys.path 启动（不依赖 console script 是否在 PATH）
BRIDGE_CMD=("${PYTHON_BIN}" -c "
import sys, os
sys.path.insert(0, '${REPO}/packages/claude-code-qq-bridge/src')
os.chdir('${REPO}')
from claude_code_qq_bridge.bridge import cli
sys.exit(cli())
")

start() {
    ensure_cliproxy_running || return 1
    if [ -f "${PIDFILE}" ] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
        echo "Bridge already running (pid $(cat "${PIDFILE}"))" >&2
        return 1
    fi
    echo "=== $(date '+%F %T') Bridge START (start.sh) ===" >> "${LOG_FILE}"
    # stdout+stderr 都进 bridge.log；nohup 防 SIGHUP
    nohup env BRIDGE_LOG_DIR="${LOG_DIR}" "${BRIDGE_CMD[@]}" \
        >> "${LOG_FILE}" 2>&1 &
    echo $! > "${PIDFILE}"
    echo "Started bridge, pid $! -> ${LOG_FILE}"
    sleep 2
    if kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
        echo "OK: alive (pid $(cat "${PIDFILE}"))"
    else
        echo "WARN: process exited immediately — tail ${LOG_FILE}" >&2
    fi
}

stop() {
    if [ ! -f "${PIDFILE}" ]; then
        echo "No pidfile (${PIDFILE}); nothing to stop" >&2
        return 0
    fi
    local pid
    pid="$(cat "${PIDFILE}")"
    if ! kill -0 "${pid}" 2>/dev/null; then
        echo "Bridge pid ${pid} not running; cleaning stale pidfile"
        rm -f "${PIDFILE}"
        return 0
    fi
    echo "=== $(date '+%F %T') Bridge STOP (start.sh) ===" >> "${LOG_FILE}"
    # 先 SIGTERM，5 秒后仍存活再 SIGKILL（只动 bridge 自身，绝不碰其它 claude）
    kill "${pid}" 2>/dev/null
    for i in $(seq 1 5); do
        kill -0 "${pid}" 2>/dev/null || { rm -f "${PIDFILE}"; echo "Stopped bridge pid ${pid}"; return 0; }
        sleep 1
    done
    kill -9 "${pid}" 2>/dev/null
    rm -f "${PIDFILE}"
    echo "Force-stopped bridge pid ${pid}"
}

status() {
    if [ -f "${PIDFILE}" ] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
        echo "Bridge running: pid $(cat "${PIDFILE}")"
        ps -o pid,etime,cmd -p "$(cat "${PIDFILE}")" | tail -1
    else
        echo "Bridge not running"
    fi
    cliproxy_status
}

case "${1:-start}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    *)       echo "Usage: $0 {start|stop|restart|status}" >&2; exit 2 ;;
esac
