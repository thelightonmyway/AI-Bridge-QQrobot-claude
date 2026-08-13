#!/usr/bin/env bash
# Claude Code QQ Bridge 统一启动/停止脚本
#
# 日志统一到 ~/agent-keep/logs/bridge.log：
#   - 程序内 logging -> FileHandler 直接写 bridge.log
#   - stdout/stderr 也一并重定向到 bridge.log（兜底捕获 print / traceback）
# 不再出现"程序以为写在 bridge.log，实际却在 nohup.out"的混乱。
set -u

REPO="${HOME}/agent-keep"
LOG_DIR="${BRIDGE_LOG_DIR:-${HOME}/agent-keep/logs}"
LOG_FILE="${LOG_DIR}/bridge.log"
PIDFILE="${LOG_DIR}/bridge.pid"

mkdir -p "${LOG_DIR}"

# 与当前运行方式一致的入口（未安装 console script，用 python -c 注入 sys.path）
# 指定带 aiohttp 的 Python：原 bridge 运行在 miniforge py 环境。
PYTHON_BIN="${BRIDGE_PYTHON:-/home/xuyang/miniforge3/envs/py/bin/python3}"
if ! "${PYTHON_BIN}" -c "import aiohttp" 2>/dev/null; then
    echo "WARN: ${PYTHON_BIN} lacks aiohttp, falling back to python3" >&2
    PYTHON_BIN="$(command -v python3)"
fi
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
