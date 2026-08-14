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

# 用 python -c 注入 sys.path 启动（不依赖 console script 是否在 PATH）
BRIDGE_CMD=("${PYTHON_BIN}" -c "
import sys, os
sys.path.insert(0, '${REPO}/packages/claude-code-qq-bridge/src')
os.chdir('${REPO}')
from claude_code_qq_bridge.bridge import cli
sys.exit(cli())
")

start() {
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
}

case "${1:-start}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    *)       echo "Usage: $0 {start|stop|restart|status}" >&2; exit 2 ;;
esac
