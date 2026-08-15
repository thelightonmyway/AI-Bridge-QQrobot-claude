#!/usr/bin/env python3
"""
claude-code-qq-bridge.py - Claude Code QQ Bridge

Architecture:
  QQ → bridge → tmux send-keys → Claude Code (interactive mode)
     ↑                                      ↓
     +—— session file: waitingFor → send button
     +—— JSONL: assistant text → push reply
     +—— QQ button → tmux send-keys → Claude continues

Principles:
  - Single session保活
  - Only read fixed structure fields, no content analysis
  - Two independent channels: session status + JSONL
  - Cache only for restart detection
  - No group messages
  - No Future/state machine
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict
from pathlib import Path

# ================= .env 配置加载 =================
def load_env():
    """极简 .env 解析，零依赖"""
    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path.home() / "AI-Bridge-QQrobot-claude" / ".env",
    ]
    for p in candidates:
        try:
            if not p.exists():
                continue
        except PermissionError:
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    # Direct assignment to ensure .env overrides inherited env vars
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")
            break
        except Exception:
            pass

load_env()

# Clear TMUX inherited env variables to prevent socket connection errors
os.environ.pop("TMUX", None)
os.environ.pop("TMUX_PANE", None)

APP_ID = os.environ.get("APP_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")
MASTER_OPENID = os.environ.get("MASTER_OPENID", "")
TMUX_SESSION = os.environ.get("TMUX_SESSION", "1")
def path_to_claude_project(path: str) -> str:
    """将文件系统路径转为 Claude Code 项目名。例如 /home/alice → -home-alice"""
    abspath = str(Path(path).resolve())
    return "-" + abspath.lstrip("/").replace("/", "-")


CLAUDE_HOME = str(Path.home() / ".claude")
CLAUDE_PROJECT = path_to_claude_project(str(Path.home()))


# === ANSI 控制字符清理 ===
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[@-_].|\x1b\[[0-9;]*m')
def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


# ═══════════════════════════════════════════════════════════════
# BTW 面板：零中断发送 + 官方 c 复制 raw Markdown 读取
# ═══════════════════════════════════════════════════════════════
# Claude Code 原生 /btw 的回答只存在 TUI 面板内存中，不写任何 JSONL。
# 官方文档（interactive-mode#side-questions-with-btw）：
#   * overlay 会主动显示最近 5 条旧 /btw 历史 —— 直接解析终端正文
#     必然混入旧回答与 UI 文本（旧实现据此踩坑）；
#   * 官方建议按 `c`：把“当前这一条 answer”的 raw Markdown 复制到
#     clipboard，而不是从终端显示内容提取。
# 本环境（WSL + tmux 3.2a，set-clipboard external + xterm clipboard）实测：
#   * `c` 通过 OSC52 复制，tmux 捕获并新建一个 buffer（bufferN，编号只增
#     不重用）；Windows clipboard（powershell Get-Clipboard）在该环境不可用；
#   * 因此读取“复制后新建的那个 buffer”= 当前 answer 的 raw Markdown，
#     无历史、无 UI、Markdown 表格原样保留，长文本完整。
# capture-pane 现在只用于 overlay 是否出现 / 状态检测，不再作为正文来源。
_BTW_HINT_END_RE = re.compile(r'Esc to close')
_BTW_Q_RE = re.compile(r'^\s*(/btw|/by-the-way)\b', re.IGNORECASE)


def _btw_panel_is_open(text: str) -> bool:
    """BTW 面板是否打开（出现底部提示行、问题行或 Answering）。"""
    for line in text.split("\n"):
        if _BTW_HINT_END_RE.search(line) or _BTW_Q_RE.match(line):
            return True
        if "Answering" in line:
            return True
    return False


def _tmux_buffer_names() -> list:
    """当前 tmux 的 buffer 名列表（如 ['buffer3', 'buffer5']）。"""
    try:
        r = subprocess.run(
            ["tmux", "list-buffers", "-F", "#{buffer_name}"],
            capture_output=True, text=True, timeout=5,
        )
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception as e:
        logger.warning(f"[btw-copy] list-buffers error: {e}")
        return []


def _tmux_buffer_num(name: str) -> int:
    d = "".join(ch for ch in name if ch.isdigit())
    return int(d) if d.isdigit() else 0


def _tmux_newest_buffer_after(before: int):
    """buffer 号 > before 的最新 buffer，返回 (buffer名, 内容)；没有则 (None, '')。

    before 是复制前记录的最大 buffer 号（sentinel）：只认复制后新建的
    buffer，绝不会读到旧内容。tmux 的 buffer 编号只增不重用（实测删除后
    下次仍是更大的新号）。
    """
    best_num, best_name, best_content = before, None, ""
    for name in _tmux_buffer_names():
        num = _tmux_buffer_num(name)
        if num <= before or num <= best_num:
            continue
        try:
            r = subprocess.run(
                ["tmux", "show-buffer", "-b", name],
                capture_output=True, text=True, timeout=5,
            )
        except Exception as e:
            logger.warning(f"[btw-copy] show-buffer error: {e}")
            continue
        best_num, best_name, best_content = num, name, r.stdout
    return best_name, best_content


async def _btw_copy_answer(max_wait: float = 4.0) -> str:
    """按 c 把当前 BTW answer 的 raw Markdown 复制到 tmux buffer 并读取。

    记录复制前最大 buffer 号，按 c 后轮询等待出现更新的 buffer，返回其
    内容，并在读取成功后删除该 buffer（保持 buffer 列表不膨胀）。返回空串
    表示复制未生成新 buffer（overlay 已关闭或复制失败）。
    """
    before_names = _tmux_buffer_names()
    before = max([_tmux_buffer_num(n) for n in before_names] or [0])
    logger.info(f"[btw-copy] buffers_before={before_names} (max={before}) 发送 c")
    await _tmux_send_key("c", pause=0.3)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        await asyncio.sleep(0.2)
        name, content = _tmux_newest_buffer_after(before)
        if name is not None:
            after_names = _tmux_buffer_names()
            logger.info(
                f"[btw-copy] buffers_after_c={after_names} selected_buffer={name} "
                f"clipboard_len={len(content)} clipboard_first_100={content[:100]!r} "
                f"clipboard_last_100={content[-100:]!r} answer_source=tmux_clipboard"
            )
            subprocess.run(["tmux", "delete-buffer", "-b", name],
                           capture_output=True, text=True, timeout=5)
            return content
    logger.warning(
        f"[btw-copy] 复制失败: 按 c 后 {max_wait}s 内未出现新 buffer "
        f"(buffers_before={before_names}) answer_source=COPY_FAILED"
    )
    return ""


# === 快速抓取（不等待稳定，用于轮询） ===
async def _capture_pane() -> str:
    """Capture tmux pane once, strip ANSI, return text."""
    proc = await asyncio.create_subprocess_exec(
        "tmux", "capture-pane", "-t", f"{TMUX_SESSION}:", "-p",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return strip_ansi(stdout.decode("utf-8", errors="replace"))


# === /btw 专用的 tmux 按键封装（核心：一律不发 Escape） ===
async def _tmux_send_key(key: str, pause: float = 0.3) -> None:
    """向 Claude pane 发送一个命名的 tmux 键（Enter/Escape/Up/Down…）。"""
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
    )
    await proc.communicate()
    if pause:
        await asyncio.sleep(pause)


async def _tmux_send_literal(text: str, pause: float = 0.3) -> None:
    """向 Claude pane 发送字面文本（-l：'Tab'/'Down' 等原样输入，不做键名解释）。"""
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "-l", text
    )
    await proc.communicate()
    if pause:
        await asyncio.sleep(pause)


async def _send_btw_command(question: str, pre_submit: str) -> bool:
    """发送 /btw：直接输入命令 + Enter，绝不发 Escape。

    Escape 是主任务被中断的根因（"esc to interrupt"），因此发送路径零 Escape。
    主任务完成/重绘的过渡期偶会吞掉 Enter，导致命令留在输入框；
    因此提交后轮询面板确认已注册（出现 Answering 或“新出现的”缩进问题行），
    未注册则重发（最多 3 次）。
    """
    pre_lines = set(pre_submit.split("\n"))
    q_probe = question[:20].lower()
    for attempt in range(1, 4):
        await _tmux_send_literal(f"/btw {question}", pause=0.3)
        await _tmux_send_key("Enter", pause=0.5)
        registered = False
        for _ in range(16):  # 最多等 8s
            await asyncio.sleep(0.5)
            text = await _capture_pane()
            if "answering" in text.lower():
                registered = True
                break
            for ln in text.split("\n"):
                # 必须是“提交前不存在”的新行，避免新问题与旧问题前 20 字符
                # 相同导致的误判；面板问题行是“缩进 + /btw”，输入框以 ❯ 开头。
                if ln not in pre_lines and re.match(
                    rf'^\s+/btw\b.*{re.escape(q_probe)}', ln, re.I
                ):
                    registered = True
                    break
            if registered:
                break
        if registered:
            return True
        logger.warning(f"[BTW] 提交未生效（可能被主任务过渡期吞掉 Enter），重试 {attempt}/3")
    return False


async def _wait_btw_answer(pre_submit: str, timeout: float = 240.0):
    """等待 /btw 回答完成，返回完成瞬间的面板文本（超时返回 None）。

    完成判定不依赖整帧稳定（后台主任务输出可能在持续变化）：
      * 主路径：曾看到 "Answering"（确认本次提交已被处理），随后底部提示
        变为完成态（含 "c to copy"/"f to fork"）；
      * 兜底：面板已变化、无 "Answering"、连续 4 帧相同（极短回答适用）。
    """
    deadline = time.time() + timeout
    prev = None
    stable = 0
    saw_answering = False
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        cur = await _capture_pane()
        low = cur.lower()
        done_hint = ("c to copy" in low) or ("f to fork" in low)
        has_answering = "answering" in low
        if has_answering:
            saw_answering = True
        if prev is None:
            prev = cur
            continue
        if cur != prev:
            stable = 0
        else:
            stable += 1
        prev = cur
        if saw_answering and done_hint:
            # 面板在回答完成后约 0.5s 内会关闭，等待越长越容易错过；只留少许抖动余量
            await asyncio.sleep(0.15)
            return cur
        changed = cur != pre_submit
        if changed and not has_answering and stable >= 4:
            await asyncio.sleep(0.15)
            return cur
    logger.warning("[BTW] 等待回答完成超时")
    return None




# === tmux 命令锁，防止并发操作 ===
_cmd_lock = asyncio.Lock()


# === capture-pane 稳定版：等待输出不动后再抓取 ===
async def capture_pane_stable(timeout: float = 15.0, settle: float = 0.6) -> str:
    """Capture tmux pane, wait for output to stabilize, strip ANSI. Returns cleaned text."""
    deadline = time.time() + timeout
    prev_hash = None
    prev_text = ""
    while time.time() < deadline:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "capture-pane", "-t", f"{TMUX_SESSION}:", "-p",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        cur = stdout.decode("utf-8", errors="replace")
        cur_hash = hash(cur)
        if prev_hash is not None and cur_hash == prev_hash:
            return strip_ansi(cur)
        prev_text = cur
        prev_hash = cur_hash
        await asyncio.sleep(settle)
    logger.warning("[Capture] Timeout, returning last frame")
    return strip_ansi(prev_text) if prev_text else ""


API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
GATEWAY_URL_PATH = "/gateway"
CONNECT_TIMEOUT = 20
RECONNECT_BACKOFF = [2, 5, 10, 30, 60]
HEARTBEAT_INTERVAL = 15.0

# === 日志：固定到 ~/AI-Bridge-QQrobot-claude/logs/bridge.log（绝对路径，与启动 CWD/重定向无关）===
# 只使用 FileHandler：避免 stdout 重定向与文件重复写两份、以及
# "程序以为写在 bridge.log，实际却跑到 nohup.out" 的混乱。
# stdout/stderr 由 start.sh 一并重定向到 bridge.log，兜底捕获未走 logging 的
# print / traceback；所有结构化日志则统一进 bridge.log。
LOG_DIR = Path(os.environ.get("BRIDGE_LOG_DIR", str(Path.home() / "AI-Bridge-QQrobot-claude" / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
BRIDGE_LOG_FILE = LOG_DIR / "bridge.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(str(BRIDGE_LOG_FILE), encoding="utf-8")],
)
logger = logging.getLogger("claude_code_bridge")
logger.info(f"[log] Bridge log file: {BRIDGE_LOG_FILE}")


def _log_uncaught(exc_type, exc, tb):
    """把未被 except 捕获的异常也写进 bridge.log。"""
    import traceback as _tb
    logger.error("Uncaught exception:\n" + "".join(_tb.format_exception(exc_type, exc, tb)))


sys.excepthook = _log_uncaught

# === State: single session保活 ===
_session_id: Optional[str] = None       # QQ WebSocket session_id (for resume)
_claude_session_id: Optional[str] = None  # Claude Code session UUID
_log_path: Optional[str] = None
_pid: Optional[int] = None
_session_file: Optional[Path] = None
_jsonl_watermark: int = 0
_current_cwd: str = str(Path.home())       # dynamically updated by /cd, /resume, refresh
_current_project: str = path_to_claude_project(_current_cwd)  # derived from _current_cwd; used by /resume listing

_access_token: Optional[str] = None
_token_expires_at: float = 0.0
_ws = None
_http_client = None
_running = False
_last_seq: Optional[int] = None
_last_msg_id: Optional[str] = None
_last_typing_sent_time = 0.0  # 记录上次发送“正在输入”通知的时间戳
_is_generating = False  # 是否处于等待 AI 响应的生成状态
_generating_since = 0.0  # 进入生成状态的时间，超时自动 reset
_bot_openid: str = ""

# === State: /resume 编号 → 会话信息映射 ===
# 每个会话保存: id(session_id), jsonl_path, cwd(target_cwd), project(target_project)
_resume_mapping: Dict[int, dict] = {}

# === State: permission mode 状态机（bridge tracking）===
# Claude Code Shift+Tab 循环顺序: Auto → Accept edits → Plan → Manual → Auto
_MODE_CYCLE = ["Auto", "Accept edits", "Plan", "Manual"]
_tracked_mode: str = "Auto"  # 初始值：启动命令 --permission-mode auto


def _try_read_mode_from_session() -> Optional[str]:
    """尝试从 Claude Code session 文件读取 permissionMode。若无则返回 None。"""
    if not _session_file or not _session_file.exists():
        return None
    try:
        with open(_session_file) as f:
            data = json.load(f)
        return data.get("permissionMode")  # 未来版本可能有此字段
    except Exception:
        return None


# === State: 会话状态持久化 + 自动恢复限流 ===
_STATE_FILE = Path.home() / ".config" / "claude-code-qq-bridge" / "state.json"
_last_recovery_attempt = 0.0
_RECOVERY_COOLDOWN = 20.0


# === 进程/会话辅助：所有操作都限定在 bridge 自己的 tmux pane 内 ===
def _is_alive(pid) -> bool:
    """进程是否存在（kill(pid, 0) 探测）。"""
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _read_cmdline(pid) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _is_claude_process(pid) -> bool:
    """PID 对应进程是否确实是 Claude CLI（排除 bridge 自身）。

    只认 argv[0] 为 claude 的进程。script 包装进程的 cmdline 里虽然含
    "claude"（-c 'claude ...'），但它的进程名是 script，不是真正的 claude，
    不能计入 _pane_claude_pids，否则 _stop_pane_claude 会误杀包装进程。
    """
    cmd = _read_cmdline(pid)
    if not cmd:
        return False
    if "claude-code-qq-bridge" in cmd or "claude_code_qq_bridge" in cmd:
        return False
    name = cmd.split()[0].rsplit("/", 1)[-1]
    if name.startswith("claude"):
        return True
    # 兼容 npx/node 等启动方式：cmdline 含 claude，但必须排除包装进程
    return "claude" in cmd and name not in ("script", "sh", "bash", "zsh", "dash", "npm", "npx", "node")


def _tmux_pane_pids(depth: int = 4) -> set:
    """返回 bridge 自己 tmux pane 的完整进程树 PID 集合。
    先取 #{pane_pid}，再逐层取后代，避免只看到 pane 直接 PID 而漏掉
    script 包装下更深层的 claude 进程。"""
    pids: set = set()
    try:
        r = subprocess.run(
            ["tmux", "list-panes", "-t", f"{TMUX_SESSION}:", "-F", "#{pane_pid}"],
            capture_output=True, text=True, timeout=5,
        )
        for tok in r.stdout.split():
            tok = tok.strip()
            if tok.lstrip("-").isdigit():
                pids.add(int(tok))
        for _ in range(depth):
            for ppid in list(pids):
                try:
                    r = subprocess.run(
                        ["ps", "--ppid", str(ppid), "-o", "pid="],
                        capture_output=True, text=True, timeout=5,
                    )
                except Exception:
                    continue
                for tok in r.stdout.split():
                    tok = tok.strip()
                    if tok.isdigit():
                        pids.add(int(tok))
    except Exception as e:
        logger.warning(f"[pane] tmux/ps error: {e}")
    return pids


def _pane_claude_pids() -> list:
    """当前 pane 进程树中存活且确认为 claude 的 PID 列表。"""
    pane = _tmux_pane_pids()
    return sorted(p for p in pane if p > 0 and _is_alive(p) and _is_claude_process(p))


def _pane_has_claude() -> bool:
    return bool(_pane_claude_pids())


def _session_file_for_pid(pid) -> Optional[Path]:
    sf = Path(CLAUDE_HOME) / "sessions" / f"{pid}.json"
    return sf if sf.exists() else None


def _session_data_for_pid(pid) -> Optional[dict]:
    sf = _session_file_for_pid(pid)
    if not sf:
        return None
    try:
        with open(sf) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _find_pane_claude_by_session(sid: str) -> Optional[int]:
    """在 bridge 自己的 pane 中，找 sessionId==sid 且存活的 claude PID。"""
    for pid in _pane_claude_pids():
        data = _session_data_for_pid(pid)
        if data and data.get("sessionId") == sid:
            return pid
    return None


def _apply_binding(sid: Optional[str], pid: Optional[int], log_path: Optional[str]):
    """把 Bridge 绑定到 (sid, pid, jsonl)，并更新 project/cwd/watermark/state。"""
    global _claude_session_id, _log_path, _pid, _session_file, _jsonl_watermark
    global CLAUDE_PROJECT, _current_project, _current_cwd
    _claude_session_id = sid
    _pid = pid
    _log_path = log_path
    _session_file = Path(CLAUDE_HOME) / "sessions" / f"{pid}.json" if pid else None
    if log_path:
        _jsonl_watermark = _count_jsonl_lines(log_path)
        actual_project = Path(log_path).parent.name
        if actual_project != CLAUDE_PROJECT:
            logger.info(f"[bind] CLAUDE_PROJECT: {CLAUDE_PROJECT} -> {actual_project}")
            CLAUDE_PROJECT = actual_project
        if actual_project != _current_project:
            logger.info(f"[bind] _current_project: {_current_project} -> {actual_project}")
            _current_project = actual_project
    if pid:
        data = _session_data_for_pid(pid)
        if data and data.get("cwd"):
            _current_cwd = data["cwd"]
    logger.info(
        f"[bind] sid={sid}, pid={pid}, jsonl={log_path}, "
        f"project={CLAUDE_PROJECT}, cwd={_current_cwd}, watermark={_jsonl_watermark}"
    )
    _save_state()


def _save_state():
    """持久化最近会话，供 Bridge 重启后自动恢复。"""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_session_id": _claude_session_id, "cwd": _current_cwd}, f)
    except Exception as e:
        logger.warning(f"[state] save failed: {e}")


def _load_state() -> dict:
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# === 停止 / 启动 / 等待绑定（均为 pane 作用域） ===
async def _interrupt_claude_in_tmux():
    """发送一次 Ctrl+C 中断当前任务，尽量保留 Claude 进程不退出。"""
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "C-c", ""
    )
    await proc.communicate()
    await asyncio.sleep(0.5)


async def _ensure_pane_at_shell(timeout: float = 10.0) -> bool:
    """等待 pane 内不再有 claude 进程（回到 bash）。
    超时则仅向 pane 内残留的 claude PID 发 SIGTERM（绝不全局 kill）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pane_claude_pids():
            return True
        await asyncio.sleep(1.0)
    for pid in _pane_claude_pids():
        logger.warning(f"[stop] force-killing stale pane claude pid={pid}")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    await asyncio.sleep(1)
    return not _pane_claude_pids()


async def _stop_pane_claude():
    """彻底停止 bridge 自己 pane 内的 Claude（C-c 序列 + 兜底 SIGTERM）。

    C-c 在 claude 的提示符下只会中断任务而不会退出，所以这里短等 3 秒后
    必然走 SIGTERM 兜底（仅对本 pane 内的 claude PID，绝不全局 kill）。"""
    for key in ["C-c", "Enter", "C-c"]:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
        )
        await proc.communicate()
        await asyncio.sleep(0.3)
    await _ensure_pane_at_shell(timeout=3)


async def _send_tmux_keys(keys: list, gap: float = 0.3):
    """向 bridge 自己的 tmux pane 依次发送按键。"""
    for key in keys:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
        )
        await proc.communicate()
        await asyncio.sleep(gap)


def _is_workspace_trust_prompt(text: str) -> bool:
    """Claude 的 workspace trust prompt（选项 1 默认选中，按 Enter 确认）：
    'Accessing workspace:' + '❯ 1. Yes, I trust this folder' + 'Enter to confirm'。"""
    return (
        ("accessing workspace" in text or "i trust this folder" in text)
        and ("i trust this folder" in text or "enter to confirm" in text)
    )


def _is_legacy_trust_prompt(text: str) -> bool:
    """旧式 trust prompt：'trust'/'信任' + '?'/'y/n'/'yes/no'。"""
    return ("trust" in text or "信任" in text) and (
        "?" in text or "y/n" in text or "yes/no" in text
    )


async def _accept_trust_prompt_if_present(checks: int = 8, interval: float = 1.0) -> bool:
    """若出现 Claude 信任提示则自动确认，无提示则跳过（避免把按键打进输入框）。

    - workspace 提示（'Accessing workspace' + 'Yes, I trust this folder' + 'Enter to confirm'）：
      选项 1 已默认选中 → 发送 Enter 确认。
    - 旧式提示（'?'/'y/n'）：发送 '1' + Enter。
    返回是否确实发送了确认键。"""
    for _ in range(checks):
        try:
            captured = (await _capture_pane()).lower()
            if _is_workspace_trust_prompt(captured):
                await _send_tmux_keys(["Enter"])
                logger.info("[launch] workspace trust prompt accepted (Enter)")
                return True
            if _is_legacy_trust_prompt(captured):
                await _send_tmux_keys(["1", "Enter"])
                logger.info("[launch] legacy trust prompt accepted ('1' + Enter)")
                return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


async def _wait_for_resumed_binding(sid: str, timeout: float = 30.0) -> bool:
    """轮询等待恢复会话的 claude PID 出现在 pane 并完成绑定。
    - Claude 刚启动时 session 文件可能尚未生成，允许合理时间重试；
    - 等待期间若出现 trust prompt（claude 停在 'Accessing workspace'），自动跨过，
      而不是干等到超时误报启动失败。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await _accept_trust_prompt_if_present(checks=1, interval=0.1)
        pid = _find_pane_claude_by_session(sid)
        log_path = find_jsonl_path(sid)
        if pid and _is_alive(pid) and log_path:
            _apply_binding(sid, pid, log_path)
            return True
        await asyncio.sleep(1.5)
    # 最后再试一次
    await _accept_trust_prompt_if_present(checks=1, interval=0.1)
    pid = _find_pane_claude_by_session(sid)
    log_path = find_jsonl_path(sid)
    if pid and _is_alive(pid) and log_path:
        _apply_binding(sid, pid, log_path)
        return True
    logger.error(f"[Resume] timeout: no live claude PID bound for session {sid}")
    return False


async def _wait_for_any_binding(timeout: float = 30.0) -> bool:
    """全新启动：轮询直到 pane 中出现带 session 文件的 claude 并绑定。
    等待期间同样自动跨过可能出现的 trust prompt。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await _accept_trust_prompt_if_present(checks=1, interval=0.1)
        sid, pid = find_current_session()
        if sid and pid and _is_alive(pid):
            _apply_binding(sid, pid, find_jsonl_path(sid))
            return True
        await asyncio.sleep(1.5)
    logger.error("[launch] timeout: no claude bound in pane")
    return False


# === 死亡检测 + 自动恢复 ===
# _recovery_in_progress + _recovery_event：并发调用者（poll 与 send_to_claude）
# 在同一恢复窗口期撞车时，等待恢复完成而不是各自再触发一次 / 误报失败。
_recovery_in_progress = False
_recovery_event = asyncio.Event()


async def _ensure_claude_alive() -> bool:
    """发送前保证 pane 内有存活 Claude。

    - 绑定 PID 存活且在 pane 内 → OK
    - pane 内出现了新的 claude（如用户手动启动）→ 重新绑定
    - pane 内无 claude → 尝试自动恢复（claude --resume 当前 sid）；限流，防抖；
      若已有恢复在进行，等待它完成而非误报"自动恢复失败"
    返回 True 表示可以安全向 Claude 发送输入。"""
    global _pid, _claude_session_id, _last_recovery_attempt, _recovery_in_progress

    if _pid and _is_alive(_pid) and _is_claude_process(_pid) and _pid in _tmux_pane_pids():
        return True

    # 0) 已有恢复在进行 → 等它完成，再复核存活
    if _recovery_in_progress:
        logger.info("[alive] recovery in progress — waiting for it to finish")
        await _recovery_event.wait()
        return _pid and _is_alive(_pid) and _is_claude_process(_pid) and _pid in _tmux_pane_pids()

    # 1) pane 内有 claude，但绑定已失效 → 重新绑定
    pane_claude = _pane_claude_pids()
    if pane_claude:
        # claude 可能正停在 workspace trust prompt（无 session 文件）→ 先跨过
        await _accept_trust_prompt_if_present(checks=3, interval=1.0)
        sid, pid = find_current_session()
        if pid and sid:
            logger.warning(
                f"[alive] rebinding to pane claude pid={pid} sid={sid} "
                f"(was pid={_pid} sid={_claude_session_id})"
            )
            _apply_binding(sid, pid, find_jsonl_path(sid))
            return True
        # 有 claude 进程但还没有 session 文件：先等一拍
        logger.info("[alive] claude process present but session file not ready yet")
        return False

    # 2) pane 内无 claude → 自动恢复（限流，防抖）
    now = time.time()
    if now - _last_recovery_attempt < _RECOVERY_COOLDOWN:
        logger.warning("[alive] auto-recovery rate-limited; claude still dead")
        return False
    _last_recovery_attempt = now

    _recovery_in_progress = True
    _recovery_event.clear()
    try:
        sid = _claude_session_id
        cwd = _current_cwd
        logger.info(f"[alive] pane has no claude — attempting auto-recovery (sid={sid}, cwd={cwd})")
        ok, info = await restart_claude_in_tmux(cwd=cwd, resume_session_id=sid)
        if ok:
            logger.info("[alive] auto-recovery OK")
            return True
        logger.error(f"[alive] auto-recovery FAILED: {info}")
        return False
    finally:
        _recovery_in_progress = False
        _recovery_event.set()


# === /resume: 扫描最近会话（增强版） ===
def _format_size(bytes_val: int) -> str:
    if bytes_val < 1024:
        return f"{bytes_val}B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f}KB"
    else:
        return f"{bytes_val / (1024 * 1024):.1f}MB"

def _estimate_tokens_from_jsonl(jf: Path) -> str:
    """从 JSONL 估算 token 用量。优先读取 usage 字段，否则统计文本量。"""
    total_usage = 0
    text_chars = 0
    try:
        with open(jf, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 优先用 usage 字段（顶层 / message 内两层都算，含缓存 token）
                usage = obj.get("usage")
                if isinstance(usage, dict):
                    total_usage += (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                    )
                elif isinstance(obj.get("message"), dict):
                    msg_usage = obj["message"].get("usage")
                    if isinstance(msg_usage, dict):
                        total_usage += (
                            msg_usage.get("input_tokens", 0)
                            + msg_usage.get("output_tokens", 0)
                            + msg_usage.get("cache_creation_input_tokens", 0)
                            + msg_usage.get("cache_read_input_tokens", 0)
                        )
                # 同时统计 user/assistant 文本量作为后备
                if obj.get("type") in ("user", "assistant"):
                    msg = obj.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_chars += len(block.get("text", ""))
                    elif isinstance(content, str):
                        text_chars += len(content)
    except Exception:
        pass
    if total_usage > 0:
        if total_usage >= 1000:
            return f"{total_usage / 1000:.0f}K tokens"
        return f"{total_usage} tokens"
    # 后备：粗略估算 (4 chars ≈ 1 token)
    estimated = max(1, text_chars // 4)
    if estimated >= 1000:
        return f"~{estimated / 1000:.0f}K tokens (估)"
    return f"~{estimated} tokens (估)"

def extract_cwd_from_jsonl(jsonl_path: str) -> Optional[str]:
    """从 JSONL 提取真实工作目录：返回第一条带 cwd 字段记录的值。
    这是会话启动时的真实 cwd，是 /resume 的权威来源。"""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = obj.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except Exception:
        pass
    return None


def project_name_to_cwd(project_name: str) -> Optional[str]:
    """项目名反向推导 cwd（如 -mnt-e-Antarctic -> /mnt/e/Antarctic）。
    仅当推导出的目录真实存在时返回，否则 None（只作 JSONL 不可用时的兜底）。"""
    if not project_name.startswith("-"):
        return None
    candidate = "/" + project_name[1:].replace("-", "/")
    return candidate if os.path.isdir(candidate) else None


def list_recent_sessions(limit: int = 10) -> list:
    """扫描 _current_project 目录，提取最近 N 个会话的摘要。
    返回列表，每个元素: {id, time, title, mtime, size, tokens, is_current}"""
    project_dir = Path(CLAUDE_HOME) / "projects" / _current_project
    if not project_dir.exists():
        return []
    sessions = []
    for jf in sorted(project_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True):
        sid = jf.stem
        mtime = jf.stat().st_mtime
        mtime_str = time.strftime("%m-%d %H:%M", time.localtime(mtime))
        file_size = jf.stat().st_size
        # 提取第一条用户消息作为标题
        title = "(空会话)"
        try:
            with open(jf, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "user":
                        msg = obj.get("message", {})
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            texts = []
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    t = block.get("text", "").strip()
                                    if t:
                                        texts.append(t)
                            content = " ".join(texts)
                        if isinstance(content, str) and content.strip():
                            title = content.strip()[:80]
                            break
        except Exception:
            pass
        tokens_str = _estimate_tokens_from_jsonl(jf)
        is_current = (sid == _claude_session_id) if _claude_session_id else False
        sessions.append({
            "id": sid,
            "jsonl_path": str(jf),
            "project": project_dir.name,
            "cwd": extract_cwd_from_jsonl(str(jf)) or project_name_to_cwd(project_dir.name),
            "time": mtime_str,
            "title": title,
            "mtime": mtime,
            "size": _format_size(file_size),
            "tokens": tokens_str,
            "is_current": is_current,
        })
        if len(sessions) >= limit:
            break
    return sessions


def find_jsonl_path(session_id: str) -> Optional[str]:
    """Given a session_id, search all ``~/.claude/projects/*/<session_id>.jsonl``
    to find the actual JSONL file on disk. Returns the path or None."""
    projects_dir = Path(CLAUDE_HOME) / "projects"
    if not projects_dir.exists():
        return None
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            logger.info(
                f"[find_jsonl_path] session_id={session_id} -> {candidate} "
                f"(project={project_dir.name})"
            )
            return str(candidate)
    logger.warning(
        f"[find_jsonl_path] session_id={session_id} NOT FOUND in any project "
        f"under {projects_dir}"
    )
    return None


def find_current_session():
    """在 bridge 自己的 tmux pane 内查找当前交互式 Claude 会话。

    只考虑 pane 进程树里的 claude 进程（并核对 session 文件）。
    绝不绑定 pane 外的 Claude（避免误接管/误操作用户其他终端里的会话）。

    Returns (session_id, pid) or (None, None) on failure.
    The JSONL path is resolved separately via find_jsonl_path()."""
    pane_pids = _tmux_pane_pids()
    logger.info(f"[find_session] tmux pane PIDs: {pane_pids}")

    best_sid = None
    best_pid = None
    best_updated = 0

    for pid in sorted(pane_pids):
        if pid <= 0 or not _is_alive(pid) or not _is_claude_process(pid):
            continue
        data = _session_data_for_pid(pid)
        if not data:
            continue
        if data.get("kind") != "interactive" or data.get("entrypoint") not in ("cli", "sdk-ts"):
            continue
        sid = data.get("sessionId")
        if not sid:
            continue
        updated = data.get("updatedAt", 0)
        if updated >= best_updated:
            best_updated = updated
            best_sid = sid
            best_pid = pid

    if not best_sid:
        logger.warning("[find_session] No live interactive Claude Code session found in bridge pane")
        return None, None

    logger.info(
        f"[find_session] best: sid={best_sid}, pid={best_pid}, updated={best_updated}"
    )
    return best_sid, best_pid


def refresh_session(known_session_id: Optional[str] = None) -> bool:
    """刷新 session 绑定。

    - known_session_id 给定（如 /resume 后）：解析该会话 JSONL，并只在
      bridge 自己的 pane 里找对应 claude PID。JSONL 或 PID 尚未就绪时返回
      False（调用方 / resume 流程会轮询重试），绝不误报成功。
    - 否则：只扫描 bridge 自己 pane 内的交互式 Claude 会话。
    """
    global _claude_session_id, _log_path, _pid, _session_file, _jsonl_watermark

    if known_session_id:
        log_path = find_jsonl_path(known_session_id)
        if not log_path:
            # JSONL 还没出现：保留 sid 待 JSONL 生成
            _claude_session_id = known_session_id
            _log_path = None
            _pid = None
            _session_file = None
            _jsonl_watermark = 0
            logger.warning(
                f"[refresh_session] JSONL for {known_session_id} not ready yet; will retry"
            )
            return False
        pid = _find_pane_claude_by_session(known_session_id)
        if pid is None:
            # JSONL 已在但 pane 中还没有该会话的 claude PID
            _claude_session_id = known_session_id
            _log_path = log_path
            _pid = None
            _session_file = None
            _jsonl_watermark = _count_jsonl_lines(log_path)
            logger.warning(
                f"[refresh_session] JSONL ok but no live PID in pane for "
                f"{known_session_id}; will retry"
            )
            return False
        _apply_binding(known_session_id, pid, log_path)
        return True

    # 普通路径：只扫描 bridge 自己 pane 内的 claude
    sid, pid = find_current_session()
    if not sid:
        logger.warning("[refresh_session] No live Claude Code session found in bridge pane")
        return False
    log_path = find_jsonl_path(sid)
    _apply_binding(sid, pid, log_path)
    return True


def _count_jsonl_lines(path: str) -> int:
    """Count lines in JSONL file without loading content."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except IOError:
        return 0


def maybe_refresh_session() -> bool:
    """每次轮询检查绑定是否仍然健康。

    原实现只在 _session_file 消失时刷新，且 _session_file 为 None（PID 丢失）
    时直接返回 True —— 这正是 /resume 后 pid=None 永久卡死的根因。
    现在：绑定 PID 存活且在 pane 内则 OK；否则从 pane 重新扫描绑定。"""
    if _pid and _is_alive(_pid) and _is_claude_process(_pid) and _pid in _tmux_pane_pids():
        return True
    # 绑定已失效 / PID 未知：尝试从 pane 重新绑定（新 claude 可能已出现）
    sid, pid = find_current_session()
    if pid and sid:
        logger.info(
            f"[refresh_session] rebinding (was pid={_pid}, sid={_claude_session_id}) "
            f"-> pid={pid}, sid={sid}"
        )
        _apply_binding(sid, pid, find_jsonl_path(sid))
        return True
    return False


def get_session_status() -> Optional[Dict]:
    """Read session file for waitingFor field."""
    if not _session_file or not _session_file.exists():
        return None
    try:
        with open(_session_file) as f:
            data = json.load(f)
        return {
            "status": data.get("status"),
            "waitingFor": data.get("waitingFor"),
        }
    except (json.JSONDecodeError, IOError):
        return None


async def send_to_claude(message: str) -> bool:
    """Send message to Claude Code via tmux.

    发送前必须确认 pane 内真的有存活 Claude；否则绝不把输入打进 Bash，
    直接通知用户。返回是否成功送达。"""
    if not await _ensure_claude_alive():
        await send_message_rest(MASTER_OPENID, "❌ Claude Code 已退出，自动恢复失败")
        return False
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "Escape", ""
    )
    await proc.communicate()
    await asyncio.sleep(0.3)
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", message, ""
    )
    await proc.communicate()
    await asyncio.sleep(0.1)
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "Enter", ""
    )
    await proc.communicate()
    logger.info(f"[Bridge -> Claude] {message[:100]} (tmux={TMUX_SESSION}, project={_current_project})")
    return True





async def start_claude_in_tmux():
    """启动时确保 bridge 自己的 pane 里有 Claude，并绑定到它。

    - pane 已有 claude → 直接绑定；
    - pane 无 claude → 启动（优先恢复上次会话，其次全新启动）。"""
    proc = await asyncio.create_subprocess_exec(
        "tmux", "has-session", "-t", f"{TMUX_SESSION}:",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode != 0:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "new-session", "-d", "-s", TMUX_SESSION,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        await asyncio.sleep(1)

    if _pane_has_claude():
        # claude 可能正停在 workspace trust prompt（有进程但还没有 session 文件）：
        # 先跨过 prompt，再等 session 文件出现并绑定；实在绑定不了才走重启。
        await _accept_trust_prompt_if_present(checks=5, interval=1.0)
        if await _wait_for_any_binding(timeout=20):
            return
        sid, pid = find_current_session()
        if pid and sid:
            _apply_binding(sid, pid, find_jsonl_path(sid))
            return
        logger.warning("[startup] claude present but no session bound; will restart")

    # pane 无 claude → 启动（优先恢复上次会话）
    state = _load_state()
    resume_sid = state.get("last_session_id")
    start_cwd = state.get("cwd") or _current_cwd
    if resume_sid and find_jsonl_path(resume_sid):
        logger.info(f"[startup] auto-resume last session {resume_sid} (cwd={start_cwd})")
        ok, info = await restart_claude_in_tmux(cwd=start_cwd, resume_session_id=resume_sid)
        if ok:
            return
        logger.warning(f"[startup] auto-resume failed ({info}), starting fresh")
    await restart_claude_in_tmux(cwd=_current_cwd)


async def stop_claude_in_tmux():
    """发送一次 Ctrl+C 中断当前任务，尽量保留 Claude 进程（供 /stop 使用）。"""
    await _interrupt_claude_in_tmux()
    if _pane_has_claude():
        logger.info("Sent Ctrl+C to Claude (interrupt, claude still alive)")
    else:
        logger.info("Sent Ctrl+C to Claude (claude exited; will auto-recover on next message)")


async def restart_claude_in_tmux(cwd: Optional[str] = None, resume_session_id: Optional[str] = None):
    """彻底重启 bridge 自己 pane 内的 Claude，并等待绑定成功。

    - 先停掉 pane 内现有 Claude（C-c + 兜底 SIGTERM，只操作自己的 pane）；
    - 确认 pane 回到 shell 后再启动，避免命令被打进旧 Claude 输入框；
    - 轮询等待新 Claude 的 PID/session 文件出现并绑定；
    - 只有完成绑定才返回 (True, info)；否则返回 (False, reason)，
      绝不在 PID 缺失时谎报 "restarted"。

    Returns (ok: bool, info: str)。"""
    global _current_cwd, _current_project, _last_recovery_attempt, CLAUDE_PROJECT
    # 重启本身也计入恢复尝试：防止 poll 里的 _ensure_claude_alive 在本函数
    # 执行期间并发再触发一次重启（20s 冷却）
    _last_recovery_attempt = time.time()
    logger.info(f"Restarting Claude Code... (cwd={cwd or 'default'}, resume={resume_session_id or 'no'})")

    # 0. 停掉旧 Claude，并确认 pane 回到 shell
    await _stop_pane_claude()

    work_dir = str(Path(cwd).resolve()) if cwd else (_current_cwd or str(Path.home()))
    if not os.path.isdir(work_dir):
        logger.warning(f"[restart] cwd {work_dir} does not exist, falling back to HOME")
        work_dir = str(Path.home())
    if cwd:
        _current_cwd = work_dir
        _current_project = path_to_claude_project(work_dir)
        CLAUDE_PROJECT = _current_project
        logger.info(f"[Project] cwd={_current_cwd}\n[Project] project={_current_project}")
    if resume_session_id:
        logger.info(f"[Resume] launch_cwd={work_dir}")

    # 1. 启动新 Claude（在确认回到 shell 之后；先清空可能残留的半行输入）
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "C-c", ""
    )
    await proc.communicate()
    await asyncio.sleep(0.3)
    claude_cmd = "claude --permission-mode auto"
    if resume_session_id:
        claude_cmd += f" --resume {resume_session_id}"
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:",
        f"cd {work_dir} && script -q -c '{claude_cmd}' /dev/null", "Enter"
    )
    await proc.communicate()

    # 2. 等待 claude 进程出现并接受信任提示（仅在确认 claude 在 pane 内时发 '1'）
    deadline = time.time() + 20
    while time.time() < deadline and not _pane_has_claude():
        await asyncio.sleep(1.0)
    if _pane_has_claude():
        await _accept_trust_prompt_if_present()
    else:
        logger.error("[restart] claude process did not appear in pane within 20s")

    # 3. 轮询绑定（Claude 刚启动时 session 文件可能尚未生成，允许重试）
    if resume_session_id:
        ok = await _wait_for_resumed_binding(resume_session_id, timeout=30)
    else:
        ok = await _wait_for_any_binding(timeout=30)

    if ok:
        logger.info(
            f"Claude Code restarted and bound (sid={_claude_session_id}, pid={_pid}, "
            f"project={CLAUDE_PROJECT})"
        )
        return True, f"sid={_claude_session_id}, pid={_pid}"
    logger.error("[restart] Claude launch FAILED — no live claude bound in pane")
    return False, "claude did not start in the pane"


async def get_tmux_pane_cwd() -> Optional[str]:
    """查询 tmux pane 实际 cwd（用于 /resume 后校验真实启动目录）。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "display-message", "-p", "-t", f"{TMUX_SESSION}:",
            "#{pane_current_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        cwd = out.decode("utf-8", errors="replace").strip()
        return cwd or None
    except Exception:
        return None


def build_approval_keyboard() -> dict:
    """Build QQ approval button keyboard in Chinese."""
    return {
        "content": {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": "btn_allow",
                            "render_data": {"label": "✅ 允许一次", "visited_label": "已允许", "style": 1},
                            "action": {"type": 2, "permission": {"type": 2}, "data": "approve:default:allow"},
                        },
                        {
                            "id": "btn_always",
                            "render_data": {"label": "🛡️ 始终允许", "visited_label": "已始终允许", "style": 1},
                            "action": {"type": 2, "permission": {"type": 2}, "data": "approve:default:allow_always"},
                        },
                    ]
                },
                {
                    "buttons": [
                        {
                            "id": "btn_deny",
                            "render_data": {"label": "❌ 拒绝", "visited_label": "已拒绝", "style": 0},
                            "action": {"type": 2, "permission": {"type": 2}, "data": "approve:default:deny"},
                        },
                    ]
                },
            ]
        }
    }


def get_http_client():
    global _http_client
    if _http_client is None:
        import httpx
        _http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    return _http_client


async def ensure_token() -> str:
    global _access_token, _token_expires_at
    if _access_token and time.time() < _token_expires_at - 60:
        return _access_token
    client = get_http_client()
    resp = await client.post(
        TOKEN_URL,
        json={"appId": APP_ID, "clientSecret": CLIENT_SECRET},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Failed to get token: {data}")
    expires_in = int(data.get("expires_in", 7200))
    _access_token = token
    _token_expires_at = time.time() + expires_in
    logger.info(f"Token refreshed, expires in {expires_in}s")
    return token


async def get_gateway_url() -> str:
    token = await ensure_token()
    client = get_http_client()
    resp = await client.get(
        f"{API_BASE}{GATEWAY_URL_PATH}",
        headers={"Authorization": f"QQBot {token}", "User-Agent": "ClaudeCode-QQ-Bridge/3.0"},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    url = data.get("url")
    if not url:
        raise RuntimeError(f"Failed to get gateway URL: {data}")
    return url


async def send_identify(ws):
    token = await ensure_token()
    payload = {
        "op": 2,
        "d": {
            "token": f"QQBot {token}",
            "intents": (1 << 25) | (1 << 30) | (1 << 12) | (1 << 26),
            "shard": [0, 1],
            "properties": {"$os": "Linux", "$browser": "claude-code-qq-bridge", "$device": "claude-code-qq-bridge"},
        },
    }
    await ws.send_json(payload)
    logger.info("Identify sent")


async def send_resume(ws):
    payload = {
        "op": 6,
        "d": {"token": f"QQBot {_access_token}", "session_id": _session_id, "seq": _last_seq},
    }
    await ws.send_json(payload)
    logger.info(f"Resume sent (session={_session_id}, seq={_last_seq})")


# 单调递增的 msg_seq 计数器（每个 target 独立），避免 (time ^ rnd) % 65536 撞号
_msg_seq_counters: Dict[str, int] = {}


def _next_msg_seq(msg_id: str = 'default') -> int:
    """返回单调递增的 msg_seq（同一 target 内不回退、不重复）。

    QQ 频道 API 要求 msg_seq 在目标粒度内递增；旧实现用
    (time ^ random) % 65536 生成，高并发或同一秒内可能撞号。
    """
    seq = _msg_seq_counters.get(msg_id, 0) + 1
    if len(_msg_seq_counters) > 1000:
        _msg_seq_counters.clear()
        seq = 1
    _msg_seq_counters[msg_id] = seq
    return seq


_seen_messages: Dict[str, float] = {}


def is_duplicate(msg_id: str) -> bool:
    now = time.time()
    if msg_id in _seen_messages and now - _seen_messages[msg_id] < 300:
        return True
    _seen_messages[msg_id] = now
    if len(_seen_messages) > 1000:
        for k in list(_seen_messages.keys()):
            if now - _seen_messages[k] > 600:
                del _seen_messages[k]
    return False


async def send_input_notify(user_openid: str, msg_id: str) -> bool:
    """发送“正在输入”通知"""
    token = await ensure_token()
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "User-Agent": "ClaudeCode-QQ-Bridge/3.0",
    }
    msg_seq = _next_msg_seq(user_openid)
    body = {
        "msg_type": 6,
        "input_notify": {"input_type": 1, "input_second": 10},
        "msg_seq": msg_seq,
        "msg_id": msg_id,
    }

    try:
        resp = await client.post(
            f"{API_BASE}/v2/users/{user_openid}/messages",
            headers=headers, json=body, timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.error(f"Typing notify failed [{resp.status_code}]: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.error(f"Typing notify exception: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# QQ 长文本回复统一出口（send_reply）
# ═══════════════════════════════════════════════════════════════
# QQ 单条 markdown 消息内容上限约 1500 字符；留 100 字符安全余量，
# 避免特殊字符 / 计数字节偏差导致发送失败。
QQ_TEXT_SAFE_LIMIT = 1400
LONG_REPLY_NOTICE = "📄 回复内容较长，已转为 TXT 文件发送。"
LONG_REPLY_DIR = Path("/tmp/claude-code-qq-bridge")


def _ensure_long_reply_dir() -> Path:
    """确保临时目录存在，不存在则自动创建。"""
    LONG_REPLY_DIR.mkdir(parents=True, exist_ok=True)
    return LONG_REPLY_DIR


def _write_long_reply_tmp(text: str) -> Path:
    """将完整回复写入临时 UTF-8 .txt 文件，返回路径。
    文件名类似 claude_reply_20260814_232800.txt（追加微秒避免同秒冲突）。"""
    _ensure_long_reply_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    tmp = LONG_REPLY_DIR / f"claude_reply_{ts}.txt"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    return tmp


async def send_reply(user_openid: str, content: str, *, keyboard: bool = False) -> bool:
    """Claude -> QQ 文本回复的统一出口。

    - 短文本（len <= QQ_TEXT_SAFE_LIMIT）：按原样直接发送 QQ 消息。
    - 长文本：**不截断**，完整内容写入临时 .txt，先提示一句，再复用
      send_local_file（即 /sendfile 背后的上传/发送能力）把 txt 发给用户；
      无论成功失败都用 try/finally 删除临时文件。
    - keyboard=True 时跳过 fallback（授权按钮必须伴随文本，且该场景文本固定很短）。
    """
    raw = content or ""
    if not raw.strip():
        return True
    # 长度按“实际要发送的完整内容”计，且落盘必须用 raw（不 strip、不截断），
    # 保证转 txt 时零丢失。短路径也发 raw 原样。
    if keyboard or len(raw) <= QQ_TEXT_SAFE_LIMIT:
        return await _send_raw_qq_text(user_openid, raw, keyboard=keyboard)

    # —— 长文本：转临时 txt 文件发送 ——
    logger.info(
        f"[LongReply] len={len(raw)} > {QQ_TEXT_SAFE_LIMIT}, txt fallback, "
        f"openid={user_openid}"
    )
    try:
        tmp_path = _write_long_reply_tmp(raw)
    except Exception as e:
        logger.error(f"[LongReply] write tmp failed: {e}")
        return False
    logger.info(f"[LongReply] tmp file written: {tmp_path} ({len(raw)} chars)")

    await _send_raw_qq_text(user_openid, LONG_REPLY_NOTICE)
    ok = False
    try:
        result = await send_local_file(str(tmp_path), user_openid)
        ok = result.startswith("✅")
        logger.info(f"[LongReply] file send {'OK' if ok else 'FAIL'}: {result}")
    except Exception as e:
        logger.error(f"[LongReply] file send exception: {e}")
    finally:
        # 无论发送成功失败都要清理临时文件
        try:
            tmp_path.unlink(missing_ok=True)
            logger.info(f"[LongReply] tmp removed: {tmp_path}")
        except Exception as e:
            logger.error(f"[LongReply] tmp removal failed: {tmp_path}: {e}")
    return ok


async def _send_raw_qq_text(user_openid: str, content: str, *, keyboard: bool = False) -> bool:
    """底层：把一段文本按 QQ 消息直接发出（不做长度检查）。"""
    token = await ensure_token()
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "User-Agent": "ClaudeCode-QQ-Bridge/3.0",
    }
    msg_seq = _next_msg_seq(user_openid)
    body = {"markdown": {"content": content}, "msg_type": 2, "msg_seq": msg_seq}

    if keyboard:
        body["keyboard"] = build_approval_keyboard()

    try:
        resp = await client.post(f"{API_BASE}/v2/users/{user_openid}/messages", headers=headers, json=body, timeout=30.0)
        if resp.status_code >= 400:
            logger.error(f"Send failed [{resp.status_code}]: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.error(f"Send exception: {e}")
        return False


async def send_message_rest(user_openid: str, content: str, *, keyboard: bool = False) -> bool:
    """旧接口兼容别名：行为与 send_reply 完全一致（含长文本 fallback）。"""
    return await send_reply(user_openid, content, keyboard=keyboard)


# ═══════════════════════════════════════════════════════════════
# Media: QQ Bot 官方分片上传 (upload_prepare → PUT → part_finish → finalize)
# ═══════════════════════════════════════════════════════════════

import hashlib

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
_FILE_EXT = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".zip",
             ".tar", ".gz", ".7z", ".csv", ".py", ".json", ".md", ".log",
             ".html", ".css", ".sh", ".yaml", ".yml", ".toml", ".cfg",
             ".svg", ".bmp", ".gif", ".tiff", ".mp4", ".mp3"}
_IMAGE_MAX = 10 * 1024 * 1024   # 10MB
_FILE_MAX  = 100 * 1024 * 1024  # 100MB（QQ 硬限制 200MB）

# [[SEND_IMAGE:...]] / [[SEND_FILE:...]] 标记正则（仅匹配绝对路径）
_SEND_IMG_RE = re.compile(r'\[\[SEND_IMAGE:(/.+?)\]\]')
_SEND_FILE_RE = re.compile(r'\[\[SEND_FILE:(/.+?)\]\]')

# upload_part_finish 可重试错误码
_BIZ_CODE_RETRYABLE = 40093001


def _compute_file_hashes(file_path: str) -> dict:
    """单次读取文件，计算 md5 / sha1 / md5_10m（前 10002432 字节的 MD5）。"""
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    md5_10m = hashlib.md5()
    bytes_read = 0
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
            if bytes_read < 10_002_432:
                remaining = 10_002_432 - bytes_read
                md5_10m.update(chunk[:remaining])
            bytes_read += len(chunk)
    return {
        "md5": md5.hexdigest(),
        "sha1": sha1.hexdigest(),
        "md5_10m": md5_10m.hexdigest(),
        "total_size": bytes_read,
    }


def _validate_local_file(file_path: str, max_size: int) -> tuple:
    """验证本地文件。返回 (ok: bool, error_msg: str)"""
    p = Path(file_path)
    if not p.exists():
        return False, f"文件不存在: {file_path}"
    if not p.is_file():
        return False, f"不是普通文件: {file_path}"
    ext = p.suffix.lower()
    allowed = _IMAGE_EXT if max_size == _IMAGE_MAX else (_IMAGE_EXT | _FILE_EXT)
    if ext not in allowed:
        return False, f"不支持的文件类型: {ext}（支持: {', '.join(sorted(allowed))}）"
    size = p.stat().st_size
    if size > max_size:
        limit_mb = max_size / (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        return False, f"文件过大: {actual_mb:.1f}MB（限制: {limit_mb:.0f}MB）"
    return True, ""


def _get_file_type(file_path: str) -> int:
    """QQ 文件类型。1=图片, 4=文件"""
    ext = Path(file_path).suffix.lower()
    return 1 if ext in _IMAGE_EXT else 4


async def _upload_file_to_qq(file_path: str, file_type: int, openid: str) -> Optional[str]:
    """QQ 官方分片上传：prepare → PUT parts → part_finish → finalize。
    返回 file_info 字符串。失败返回 None。"""
    import httpx
    token = await ensure_token()
    base_headers = {"Authorization": f"QQBot {token}", "Content-Type": "application/json"}
    fname = Path(file_path).name
    fsize = Path(file_path).stat().st_size

    try:
        # ── Step 1: upload_prepare ──
        logger.info(f"[Media] prepare upload: {fname} ({fsize} bytes, type={file_type})")
        hashes = await asyncio.to_thread(_compute_file_hashes, file_path)
        prepare_body = {
            "file_type": file_type,
            "file_size": str(fsize),
            "file_name": fname,
            "md5": hashes["md5"],
            "sha1": hashes["sha1"],
            "md5_10m": hashes["md5_10m"],
        }
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(
                f"{API_BASE}/v2/users/{openid}/upload_prepare",
                headers=base_headers, json=prepare_body,
            )
        if resp.status_code >= 400:
            logger.error(f"[Media] prepare failed [{resp.status_code}]: {resp.text[:500]}")
            return None
        prep = resp.json()
        # 响应可能被 data 包裹
        if "data" in prep and isinstance(prep["data"], dict):
            prep = prep["data"]
        upload_id = prep.get("upload_id")
        block_size = int(prep.get("block_size", "5242880"))
        parts = prep.get("parts") or prep.get("part_list") or []
        if not upload_id or not parts:
            logger.error(f"[Media] bad prepare response: {json.dumps(prep, ensure_ascii=False)[:500]}")
            return None
        logger.info(f"[Media] upload_id={upload_id}, block_size={block_size}, parts={len(parts)}")

        # ── Step 2: PUT + part_finish per part ──
        # 本地 offset 从 0 顺序累加，不依赖 QQ 返回的 part["index"]（该值仅用于 upload_part_finish）
        local_offset = 0
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            with open(file_path, "rb") as fh:
                for display_num, part in enumerate(parts, 1):
                    api_index = int(part.get("index", part.get("part_index", 0)))
                    part_url = part.get("presigned_url", "")
                    part_size = int(part.get("block_size", block_size))

                    if part_size <= 0:
                        logger.error(
                            f"[Media] bad part_size: display={display_num} "
                            f"api_index={api_index} part_size={part_size}"
                        )
                        return None

                    # 连续读取
                    fh.seek(local_offset)
                    chunk = fh.read(part_size)

                    if len(chunk) == 0:
                        logger.error(
                            f"[Media] empty chunk: display={display_num} "
                            f"api_index={api_index} offset={local_offset} "
                            f"part_size={part_size} fsize={fsize}"
                        )
                        return None

                    logger.info(
                        f"[Media] uploading part display={display_num} "
                        f"api_index={api_index} offset={local_offset} bytes={len(chunk)}"
                    )

                    part_md5 = hashlib.md5(chunk).hexdigest()

                    # PUT 到预签名 URL
                    for put_retry in range(2):
                        put_resp = await client.put(
                            part_url, content=chunk,
                            headers={"Content-Length": str(len(chunk))},
                        )
                        if 200 <= put_resp.status_code < 300:
                            break
                        if put_retry < 1:
                            await asyncio.sleep(1.0)
                    if put_resp.status_code >= 300:
                        logger.error(
                            f"[Media] part api_index={api_index} PUT failed "
                            f"[{put_resp.status_code}]: {put_resp.text[:300]}"
                        )
                        return None

                    # upload_part_finish（使用 QQ API 返回的 api_index）
                    finish_body = {
                        "upload_id": upload_id,
                        "part_index": api_index,
                        "block_size": str(len(chunk)),
                        "md5": part_md5,
                    }
                    deadline = time.time() + 120
                    while True:
                        fin_resp = await client.post(
                            f"{API_BASE}/v2/users/{openid}/upload_part_finish",
                            headers=base_headers, json=finish_body,
                        )
                        if fin_resp.status_code < 400:
                            break
                        try:
                            err_data = fin_resp.json()
                            biz_code = err_data.get("biz_code") or err_data.get("code")
                        except Exception:
                            biz_code = None
                        if biz_code == _BIZ_CODE_RETRYABLE and time.time() < deadline:
                            logger.warning(
                                f"[Media] part api_index={api_index} finish retryable (40093001), retrying..."
                            )
                            await asyncio.sleep(1.0)
                            continue
                        logger.error(
                            f"[Media] part api_index={api_index} finish failed "
                            f"[{fin_resp.status_code}]: {fin_resp.text[:500]}"
                        )
                        return None
                    logger.info(f"[Media] part display={display_num} api_index={api_index} finished")

                    local_offset += len(chunk)

        # ── Step 3: finalize (POST /files with upload_id) ──
        logger.info(f"[Media] finalize upload, upload_id={upload_id}")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for fin_retry in range(3):
                final_resp = await client.post(
                    f"{API_BASE}/v2/users/{openid}/files",
                    headers=base_headers,
                    json={"file_type": file_type, "upload_id": upload_id},
                )
                if final_resp.status_code < 400:
                    break
                if fin_retry < 2:
                    await asyncio.sleep(2.0)
        if final_resp.status_code >= 400:
            logger.error(f"[Media] finalize failed [{final_resp.status_code}]: {final_resp.text[:500]}")
            return None
        result = final_resp.json()
        if "data" in result and isinstance(result["data"], dict):
            result = result["data"]
        file_info = result.get("file_info") or result.get("file_uuid")
        if not file_info:
            logger.error(f"[Media] no file_info in finalize: {json.dumps(result, ensure_ascii=False)[:300]}")
            return None
        logger.info(f"[Media] file_info received: {file_info[:50]}...")
        return file_info

    except Exception as e:
        logger.error(f"[Media] upload exception: {e}")
        return None


async def _send_media_message(file_info: str, openid: str) -> bool:
    """发送 QQ 富媒体消息（msg_type=7）。"""
    token = await ensure_token()
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "User-Agent": "ClaudeCode-QQ-Bridge/3.0",
    }
    body = {"msg_type": 7, "media": {"file_info": file_info}, "msg_seq": _next_msg_seq(openid)}
    try:
        resp = await client.post(
            f"{API_BASE}/v2/users/{openid}/messages",
            headers=headers, json=body, timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.error(f"[Media] QQ send failed [{resp.status_code}]: {resp.text[:300]}")
            return False
        logger.info(f"[Media] QQ send success")
        return True
    except Exception as e:
        logger.error(f"[Media] QQ send exception: {e}")
        return False


async def send_local_image(file_path: str, openid: str) -> str:
    """上传并发送本地图片。返回结果描述字符串。"""
    ok, err = _validate_local_file(file_path, _IMAGE_MAX)
    if not ok:
        return f"❌ {err}"
    file_info = await _upload_file_to_qq(file_path, 1, openid)
    if not file_info:
        return f"❌ 图片上传失败: {Path(file_path).name}"
    if await _send_media_message(file_info, openid):
        return f"✅ 图片已发送: {Path(file_path).name}"
    return f"❌ 图片发送失败: {Path(file_path).name}"


async def send_local_file(file_path: str, openid: str) -> str:
    """上传并发送本地文件。返回结果描述字符串。"""
    ok, err = _validate_local_file(file_path, _FILE_MAX)
    if not ok:
        return f"❌ {err}"
    file_type = _get_file_type(file_path)
    file_info = await _upload_file_to_qq(file_path, file_type, openid)
    if not file_info:
        return f"❌ 文件上传失败: {Path(file_path).name}"
    if await _send_media_message(file_info, openid):
        return f"✅ 文件已发送: {Path(file_path).name}"
    return f"❌ 文件发送失败: {Path(file_path).name}"


def _extract_media_markers(text: str) -> tuple:
    """扫描文本中的 [[SEND_IMAGE:...]] / [[SEND_FILE:...]] 标记。
    返回 (clean_text, media_list)，其中 media_list = [{type, path}, ...]"""
    media_list = []
    for m in _SEND_IMG_RE.finditer(text):
        media_list.append({"type": "image", "path": m.group(1)})
    for m in _SEND_FILE_RE.finditer(text):
        media_list.append({"type": "file", "path": m.group(1)})
    clean = _SEND_IMG_RE.sub('', text)
    clean = _SEND_FILE_RE.sub('', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()
    return clean, media_list


async def _send_media_from_markers(media_list: list, openid: str):
    """根据提取的 media 列表发送富媒体到 QQ。"""
    for item in media_list:
        try:
            if item["type"] == "image":
                result = await send_local_image(item["path"], openid)
            else:
                result = await send_local_file(item["path"], openid)
            logger.info(f"[Media Marker] {result}")
        except Exception as e:
            logger.error(f"[Media Marker] exception: {e}")


async def _wait_for_approval():
    """Block until approval is cleared. Returns when session leaves waiting state."""
    while True:
        status = get_session_status()
        if not status or status.get("waitingFor") != "permission prompt":
            return
        await asyncio.sleep(0.5)


def find_actions(data) -> list:
    """深度递归搜索 JSON 结构中所有的 toolAction 或 toolSummary 字段"""
    actions = []
    if isinstance(data, dict):
        ta = data.get("toolAction") or data.get("toolSummary")
        if ta and isinstance(ta, str):
            actions.append(ta)
        arg_json = data.get("argumentsJson")
        if arg_json and isinstance(arg_json, str):
            try:
                sub = json.loads(arg_json)
                sub_ta = sub.get("toolAction") or sub.get("toolSummary")
                if sub_ta and isinstance(sub_ta, str):
                    actions.append(sub_ta)
            except Exception:
                pass
        for v in data.values():
            actions.extend(find_actions(v))
    elif isinstance(data, list):
        for item in data:
            actions.extend(find_actions(item))
    return actions


async def periodic_poll():
    """Background polling: detect approval + push replies.
    Order: JSONL text first, then approval button — so user sees
    Claude's message before being asked to approve."""
    global _jsonl_watermark, _is_generating, _last_typing_sent_time, _generating_since
    global _claude_session_id, _log_path, _pid, _session_file
    global CLAUDE_PROJECT, _current_cwd, _current_project
    _poll_cycle = 0  # counter for periodic diagnostic logging
    while True:
        # 触发/续杯“正在输入中”的顶部状态
        now = time.time()
        if _is_generating and _last_msg_id and (now - _last_typing_sent_time > 2.5):
            asyncio.create_task(send_input_notify(MASTER_OPENID, _last_msg_id))
            _last_typing_sent_time = now

        # 超时自动重置“正在输入”状态（防止卡死超过 5 分钟）
        if _is_generating and _generating_since > 0 and (now - _generating_since > 300):
            logger.warning(f"[Poll] _is_generating timeout ({int(now - _generating_since)}s), auto-reset")
            _is_generating = False
            _generating_since = 0.0

        await asyncio.sleep(3)
        _poll_cycle += 1
        # Periodic diagnostic: log monitoring state every 10 cycles (~30s)
        if _poll_cycle % 10 == 0:
            jsonl_exists = bool(_log_path and Path(_log_path).exists())
            jsonl_lines = _count_jsonl_lines(_log_path) if jsonl_exists else 0
            logger.info(
                f"[Poll diag] cycle={_poll_cycle}, "
                f"claude_sid={_claude_session_id}, pid={_pid}, "
                f"project={_current_project}, cwd={_current_cwd}, "
                f"jsonl={_log_path}, jsonl_exists={jsonl_exists}, "
                f"jsonl_lines={jsonl_lines}, watermark={_jsonl_watermark}, "
                f"is_generating={_is_generating}, "
                f"session_file={str(_session_file) if _session_file else 'None'}"
            )
        try:
            # 0. Refresh session if process died
            if not maybe_refresh_session():
                # pane 无存活 Claude：尝试自动恢复（带限流）；恢复失败则跳过本周期
                if not await _ensure_claude_alive():
                    continue

            # 1. Read JSONL for new assistant replies (BEFORE approval check)
            new_texts = []
            if _log_path and Path(_log_path).exists():
                with open(_log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                curr_lines = len(lines)
                new_lines = lines[_jsonl_watermark:curr_lines]
                if new_lines:
                    _jsonl_watermark = curr_lines
                    for line in new_lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("type") == "assistant":
                            content = obj.get("message", {}).get("content", [])
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    t = block.get("text", "").strip()
                                    if t:
                                        new_texts.append(t)
            else:
                # JSONL file missing — try to recover
                if _claude_session_id:
                    # If we have a session_id but no JSONL (e.g., after /resume),
                    # retry find_jsonl_path — the JSONL may have appeared
                    retry_path = find_jsonl_path(_claude_session_id)
                    if retry_path:
                        logger.info(
                            f"[Poll] JSONL appeared! {retry_path} — rebinding watcher"
                        )
                        _log_path = retry_path
                        # Update project tracking from the found path
                        actual_project = Path(retry_path).parent.name
                        _current_project = actual_project
                        if actual_project != CLAUDE_PROJECT:
                            logger.info(
                                f"[Poll] CLAUDE_PROJECT updated: {CLAUDE_PROJECT} -> {actual_project}"
                            )
                            CLAUDE_PROJECT = actual_project
                        logger.info(
                            f"[Project] project={_current_project}\n"
                            f"[Watcher] path={_log_path}"
                        )
                        # Skip old lines, only capture new output
                        _jsonl_watermark = _count_jsonl_lines(retry_path)
                        logger.info(f"[Watcher] watermark={_jsonl_watermark}")
                    else:
                        logger.warning(
                            f"[Poll] JSONL still missing for claude_sid={_claude_session_id}. "
                            f"project={_current_project}. Will retry."
                        )
                else:
                    logger.warning(
                        f"[Poll] JSONL file missing: {_log_path}. "
                        f"claude_sid={_claude_session_id}, CLAUDE_PROJECT={CLAUDE_PROJECT}. "
                        f"Attempting session refresh..."
                    )
                    if not refresh_session():
                        logger.error(
                            f"[Poll] Session refresh failed — no live Claude Code session. "
                            f"Will retry in next poll cycle."
                        )

            # 2. Check approval status (session file)
            status = get_session_status()
            approval_pending = status and status.get("waitingFor") == "permission prompt"
            is_idle = status and status.get("status") in ("idle", "shell")

            if is_idle:
                _is_generating = False
                _generating_since = 0.0

            if approval_pending:
                _is_generating = False  # 进入等待授权，关闭输入状态
                _generating_since = 0.0
                # Send text first, then media markers, then approval button
                if new_texts:
                    reply = "\n\n".join(new_texts)
                    clean_reply, media_list = _extract_media_markers(reply)
                    if clean_reply:
                        logger.info(f"[Poll -> QQ Text] {clean_reply[:80]}")
                        await send_reply(MASTER_OPENID, clean_reply)
                        await asyncio.sleep(0.3)
                    if media_list:
                        await _send_media_from_markers(media_list, MASTER_OPENID)
                        await asyncio.sleep(0.3)

                logger.info("[Poll] Approval detected, sending QQ button")
                await send_message_rest(MASTER_OPENID, "🔐 **Claude Code 需要您的确认**", keyboard=True)

                # Block until user handles approval
                await _wait_for_approval()
                logger.info("[Poll] Approval handled, resumed polling")
                continue

            # 3. No approval pending — push text + media
            if new_texts:
                reply = "\n\n".join(new_texts)
                clean_reply, media_list = _extract_media_markers(reply)
                if clean_reply:
                    logger.info(
                        f"[Poll -> QQ] {clean_reply[:100]} "
                        f"(from {_log_path}, {len(new_texts)} blocks)"
                    )
                    await send_reply(MASTER_OPENID, clean_reply)
                if media_list:
                    logger.info(f"[Poll -> QQ Media] {len(media_list)} file(s)")
                    await _send_media_from_markers(media_list, MASTER_OPENID)
            elif _is_generating:
                # We're expecting output but JSONL hasn't updated yet — log periodically
                pass  # silence is normal while Claude is thinking
        except Exception as e:
            logger.error(f"[Poll] error: {e}")


def _save_master_openid(openid: str):
    """Persist MASTER_OPENID to .env file."""
    global MASTER_OPENID
    # 防御：空 openid 绝不能写进 .env，否则主人绑定永久失效
    if not openid:
        logger.warning("[AutoBind] empty openid, ignoring")
        return
    if openid == MASTER_OPENID:
        return
    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path.home() / "AI-Bridge-QQrobot-claude" / ".env",
    ]
    for p in candidates:
        try:
            if not p.exists():
                continue
        except PermissionError:
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
            found = False
            for i, line in enumerate(lines):
                if line.startswith("MASTER_OPENID="):
                    lines[i] = f"MASTER_OPENID={openid}\n"
                    found = True
                    break
            if not found:
                lines.append(f"MASTER_OPENID={openid}\n")
            p.write_text("".join(lines), encoding="utf-8")
            MASTER_OPENID = openid
            logger.info(f"[AutoBind] MASTER_OPENID updated -> {openid}")
            return
        except Exception as e:
            logger.error(f"[AutoBind] Failed to save: {e}")
    # Fallback: write to first candidate
    try:
        candidates[0].write_text(f"MASTER_OPENID={openid}\n", encoding="utf-8")
        MASTER_OPENID = openid
        logger.info(f"[AutoBind] MASTER_OPENID updated (new file) -> {openid}")
    except Exception as e:
        logger.error(f"[AutoBind] Fallback save failed: {e}")


async def handle_c2c_message(d: dict):
    """Handle C2C message from QQ user. Supports text + attachments (images/files)."""
    global _last_msg_id, _bot_openid, _is_generating, _tracked_mode, _resume_mapping, _generating_since
    msg_id = str(d.get("id", ""))
    if not msg_id or is_duplicate(msg_id):
        return
    content = str(d.get("content", "")).strip()
    attachments = d.get("attachments") if isinstance(d.get("attachments"), list) else []
    author = d.get("author") if isinstance(d.get("author"), dict) else {}
    user_openid = str(author.get("user_openid", ""))
    if not user_openid:
        return
    if not content and not attachments:
        return
    _last_msg_id = msg_id
    _is_generating = True
    _generating_since = time.time()
    logger.info(f"[Recv] openid={user_openid}: content={content[:50]}, attachments={len(attachments)}")

    # Auto-bind: if MASTER_OPENID is empty or a new sender appears, adopt it
    if not MASTER_OPENID or user_openid != MASTER_OPENID:
        old = MASTER_OPENID
        _save_master_openid(user_openid)
        if old:
            logger.warning(f"[Recv] MASTER_OPENID changed: {old} -> {user_openid}")

    # Approval button callback
    if content.startswith("approve:"):
        _is_generating = True
        _generating_since = time.time()
        parts = content.split(":")
        if len(parts) >= 3:
            keystroke = {"allow": "1", "allow_always": "2", "deny": "3"}.get(parts[2])
            if keystroke:
                if not _pane_has_claude():
                    logger.warning("[Approval] claude not alive in pane — NOT sending keystroke to bash")
                    return
                logger.info(f"[Approval] Sending keystroke: {keystroke}")
                proc = await asyncio.create_subprocess_exec(
                    "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", keystroke, ""
                )
                await proc.communicate()
        return

    # ═══════════════════════════════════════════════════════════
    # Command Routing: 所有特殊命令在此分发，处理后必须 return
    # ═══════════════════════════════════════════════════════════
    lower = content.strip().lower()

    # --- A. /stop（bridge 自己处理，不需要锁）---
    if lower in ["/stop", "/tingzhi", "/kill"]:
        _is_generating = False
        logger.info("[Recv] Stop command")
        await stop_claude_in_tmux()
        await send_message_rest(user_openid, "⛔ Interrupted.")
        return

    # --- A. /resume（bridge 自己处理）---
    if lower.startswith(("/resume", "/huifu", "/history")):
        _is_generating = False
        raw = content.strip()
        parts = raw.split(None, 1)

        # /resume N → 恢复指定会话（需要锁）
        if len(parts) == 2 and parts[1].strip().isdigit():
            idx = int(parts[1].strip())
            entry = _resume_mapping.get(idx)
            if not entry:
                await send_message_rest(user_openid, "⚠️ 未找到对应会话，请先发送 /resume 查看列表")
                return
            sid = entry.get("id")
            logger.info(f"[Recv] /resume {idx} -> session_id={sid}")
            # Look up the target JSONL path before restarting so we can log it
            target_jsonl = entry.get("jsonl_path") or find_jsonl_path(sid)
            # 真实 target_cwd：优先从目标 JSONL 读取（会话启动时记录），
            # 其次用列表时已提取的值，最后尝试从项目名反向推导。
            # 禁止回退到 HOME / bridge 启动目录 —— 解析不到就中止恢复。
            target_cwd = (
                (extract_cwd_from_jsonl(target_jsonl) if target_jsonl else None)
                or entry.get("cwd")
                or (project_name_to_cwd(Path(target_jsonl).parent.name) if target_jsonl else None)
            )
            logger.info(
                f"[Resume] target session_id={sid}\n"
                f"[Resume] target jsonl={target_jsonl}\n"
                f"[Resume] target_cwd={target_cwd}\n"
                f"[Resume] current project={_current_project}"
            )
            if not target_cwd or not os.path.isdir(target_cwd):
                logger.error(
                    f"[Resume] ABORT: cannot resolve valid target_cwd for session "
                    f"{sid} (jsonl={target_jsonl})"
                )
                await send_message_rest(
                    user_openid,
                    "⚠️ 无法确定该会话的工作目录，已取消恢复（避免在错误目录启动）。",
                )
                return
            await send_message_rest(user_openid, f"⏳ 正在恢复会话 {idx}...")
            async with _cmd_lock:
                ok, info = await restart_claude_in_tmux(cwd=target_cwd, resume_session_id=sid)
            if not ok:
                logger.error(f"[Resume] FAILED to restore session {sid}: {info}")
                await send_message_rest(
                    user_openid,
                    f"❌ 恢复会话 {idx} 失败：{info}。\nClaude 未能启动，请稍后重试或发送 /resume 查看列表。",
                )
                _resume_mapping.clear()
                return
            # 绑定成功后 refresh_session 已更新 _current_cwd、_current_project、
            # _log_path、watermark —— 这里只做核对与日志
            tmux_cwd = await get_tmux_pane_cwd()
            logger.info(
                f"[Resume] tmux_cwd={tmux_cwd}\n"
                f"[Resume] after restart: cwd={_current_cwd}, "
                f"project={_current_project}, jsonl={_log_path}, "
                f"watermark={_jsonl_watermark}"
            )
            await send_message_rest(
                user_openid,
                f"✅ 已恢复会话 {idx}，可以继续对话了。\n📁 cwd: {target_cwd}",
            )
            _resume_mapping.clear()
            return

        # 裸 /resume → 非阻塞列出会话（不持锁，不影响 Claude）
        logger.info(f"[Resume] listing project={_current_project}, cwd={_current_cwd}")
        sessions = await asyncio.to_thread(list_recent_sessions, 10)
        if not sessions:
            await send_message_rest(user_openid, f"📭 当前项目（{_current_project}）没有历史会话。")
            return
        _resume_mapping.clear()
        lines = [f"**📋 历史会话（{_current_project}）**\n"]
        for i, s in enumerate(sessions, 1):
            # 保存全量信息: session_id / jsonl_path / target_cwd / target_project
            _resume_mapping[i] = s
            cur = " 🟢*当前*" if s["is_current"] else ""
            lines.append(f"[{i}] `{s['time']}` [{s['size']} | {s['tokens']}]{cur}")
            lines.append(f"    {s['title'][:100]}")
        lines.append(f"\n回复 `/resume N` 恢复会话（如 `/resume 1`）")
        await send_message_rest(user_openid, "\n".join(lines))
        return

    # --- A. /cd <path>（bridge 自己处理，需要锁）---
    if lower.startswith("/cd"):
        _is_generating = False
        target_path = content.strip()[3:].strip()
        if not target_path:
            await send_message_rest(user_openid, "⚠️ 用法: /cd <路径>\n例如: /cd /mnt/e/my-project")
            return
        target = Path(target_path)
        if not target.exists():
            await send_message_rest(user_openid, f"⚠️ 目录不存在: {target_path}")
            return
        if not target.is_dir():
            await send_message_rest(user_openid, f"⚠️ 不是目录: {target_path}")
            return
        logger.info(f"[Recv] /cd command -> {target_path}")
        async with _cmd_lock:
            ok, info = await restart_claude_in_tmux(cwd=str(target))
        if not ok:
            logger.error(f"[cd] FAILED to switch to {target_path}: {info}")
            await send_message_rest(
                user_openid,
                f"❌ 切换到 {target_path} 失败：{info}",
            )
            return
        logger.info(
            f"[Project] after /cd: cwd={_current_cwd}, project={_current_project}, "
            f"jsonl={_log_path}, watermark={_jsonl_watermark}"
        )
        await send_message_rest(
            user_openid,
            f"✅ 已切换到 {target_path}\n项目: {_current_project}\n新会话已启动。"
        )
        return

    # --- A. /sendimg <path>（发送本地图片到 QQ）---
    if lower.startswith("/sendimg"):
        _is_generating = False
        img_path = content.strip()[8:].strip()
        if not img_path:
            await send_message_rest(user_openid, "⚠️ 用法: /sendimg <本地图片路径>\n例如: /sendimg /mnt/e/pics/photo.jpg")
            return
        logger.info(f"[Recv] /sendimg: {img_path}")
        result = await send_local_image(img_path, user_openid)
        await send_message_rest(user_openid, result)
        return

    # --- A. /sendfile <path>（发送本地文件到 QQ）---
    if lower.startswith("/sendfile"):
        _is_generating = False
        f_path = content.strip()[9:].strip()
        if not f_path:
            await send_message_rest(user_openid, "⚠️ 用法: /sendfile <本地文件路径>\n例如: /sendfile /mnt/e/data/report.pdf")
            return
        logger.info(f"[Recv] /sendfile: {f_path}")
        result = await send_local_file(f_path, user_openid)
        await send_message_rest(user_openid, result)
        return

    # --- A. /mode 和 /mode status（bridge 状态机）---
    if lower.startswith("/mode"):
        _is_generating = False
        parts = content.strip().split(None, 1)

        # /mode status → 仅查询，不切换
        if len(parts) == 2 and parts[1].strip().lower() == "status":
            from_session = _try_read_mode_from_session()
            if from_session:
                await send_message_rest(user_openid, f"📌 当前权限模式: **{from_session}**（来源: Claude session）")
            else:
                await send_message_rest(user_openid, f"📌 当前权限模式: **{_tracked_mode}**（来源: bridge tracking）\nClaude 启动参数: `--permission-mode auto`")
            return

        # /mode（无参数）→ 切换模式
        logger.info(f"[Recv] /mode command (tracked={_tracked_mode})")
        # 先尝试从 session 读取真实模式
        from_session = _try_read_mode_from_session()
        if from_session:
            # 如果能读到真实模式，以此为基准切换
            try:
                cur_idx = _MODE_CYCLE.index(from_session)
            except ValueError:
                cur_idx = _MODE_CYCLE.index(_tracked_mode) if _tracked_mode in _MODE_CYCLE else 0
            source = "Claude session"
        else:
            # 用 bridge 状态机
            try:
                cur_idx = _MODE_CYCLE.index(_tracked_mode)
            except ValueError:
                cur_idx = 0
            source = "bridge tracking"

        next_idx = (cur_idx + 1) % len(_MODE_CYCLE)
        next_mode = _MODE_CYCLE[next_idx]

        # 发送 BTab 到 tmux
        async with _cmd_lock:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "BTab", ""
            )
            await proc.communicate()
            await asyncio.sleep(1.0)
            # 尝试 capture-pane 验证（best effort，不阻塞）
            try:
                captured = await capture_pane_stable(timeout=4.0)
                for keyword in _MODE_CYCLE:
                    if keyword in captured:
                        next_mode = keyword
                        source = "capture-pane"
                        break
            except Exception:
                pass

        _tracked_mode = next_mode
        logger.info(f"[Mode] Switched to {next_mode} (source={source})")
        await send_message_rest(user_openid, f"🔄 权限模式已切换: **{next_mode}**\n（来源: {source}）")
        return

    # --- B. /context（TUI 命令，capture-pane 解析）---
    if lower == "/context":
        _is_generating = False
        logger.info("[Recv] /context command")
        async with _cmd_lock:
            # Send Escape to clear any popup, then /context
            for key in ["Escape", "Escape"]:
                proc = await asyncio.create_subprocess_exec(
                    "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
                )
                await proc.communicate()
                await asyncio.sleep(0.15)
            proc = await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "/context", "Enter"
            )
            await proc.communicate()
            await asyncio.sleep(1.5)
            captured = await capture_pane_stable(timeout=10.0)
        # 解析 Context Usage 行 (例: "Messages: 12.3K tokens (45%)")
        context_info = {}
        for line in captured.split("\n"):
            line = line.strip()
            if ":" in line and ("token" in line.lower() or "%" in line):
                # Clean up box-drawing chars
                clean = line.lstrip("│├└┌┐┘└─╭╰╯╭╮├┤┴┬┼ ").strip()
                if ":" in clean:
                    key, _, val = clean.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key and val:
                        context_info[key] = val
        if context_info:
            lines = ["**📊 Context Usage**\n"]
            for k, v in context_info.items():
                lines.append(f"- **{k}**: {v}")
            await send_message_rest(user_openid, "\n".join(lines))
        else:
            # Fallback: return last few relevant lines
            relevant = [l.strip() for l in captured.split("\n") if l.strip() and "token" in l.lower()]
            if relevant:
                await send_message_rest(user_openid, "**📊 Context Usage**\n" + "\n".join(relevant[-8:]))
            else:
                await send_message_rest(user_openid, "⚠️ 无法解析 context 输出，请稍后重试")
        return

    # --- B. /compact [instructions]（Claude slash command，需等待完成 + 重新绑定）---
    if lower.startswith("/compact"):
        _is_generating = False
        compact_msg = content.strip()
        logger.info(f"[Recv] /compact command: {compact_msg[:60]}")
        async with _cmd_lock:
            if not await send_to_claude(compact_msg):
                return
            # 等待 Claude 完成 compact（轮询 session status）
            await asyncio.sleep(2)
            for _ in range(60):  # max 2 min wait
                status = get_session_status()
                if status and status.get("status") in ("idle", "shell"):
                    break
                await asyncio.sleep(2)
            # 重新绑定当前 session/JSONL
            refresh_session()
            # 再发送 /context 获取压缩后的使用量
            for key in ["Escape", "Escape"]:
                proc = await asyncio.create_subprocess_exec(
                    "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
                )
                await proc.communicate()
                await asyncio.sleep(0.15)
            proc = await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "/context", "Enter"
            )
            await proc.communicate()
            await asyncio.sleep(1.5)
            captured = await capture_pane_stable(timeout=10.0)
        # 提取 token 相关行
        token_lines = [l.strip() for l in captured.split("\n") if "token" in l.lower() or "%" in l]
        if token_lines:
            await send_message_rest(user_openid, "✅ **压缩完成**\n" + "\n".join(token_lines[-6:]))
        else:
            await send_message_rest(user_openid, "✅ **压缩完成**（session 已重新绑定）")
        return

    # --- B. /clear 或 /new（重启 Claude，识别新 session）---
    if lower in ["/clear", "/new", "/reset", "/qingkong", "/xin duihua"]:
        _is_generating = False
        logger.info("[Recv] /clear command")
        async with _cmd_lock:
            ok, info = await restart_claude_in_tmux()
        if not ok:
            await send_message_rest(user_openid, f"❌ 新会话启动失败：{info}")
            return
        if _claude_session_id:
            await send_message_rest(user_openid, f"✅ 新会话已启动\nID: `{_claude_session_id[:8]}...`\n项目: {CLAUDE_PROJECT}")
        else:
            await send_message_rest(user_openid, "✅ 新会话已启动")
        return

    # --- C. /btw <question>（TUI side question，不写入 JSONL）---
    if lower.startswith(("/btw", "/by-the-way")):
        _is_generating = False
        cmd_end = content.strip().find(" ")
        btw_question = content.strip()[cmd_end:].strip() if cmd_end > 0 else ""
        if not btw_question:
            await send_message_rest(user_openid, "⚠️ 用法: /btw <问题>\n例如: /btw 这个函数的时间复杂度是多少")
            return
        logger.info(f"[Recv] /btw: {btw_question[:60]}")
        await send_message_rest(user_openid, f"💬 BTW 查询中: *{btw_question[:80]}*")

        async with _cmd_lock:
            # 先确认 pane 内有存活 Claude，绝不对 Bash 发按键
            if not await _ensure_claude_alive():
                await send_message_rest(MASTER_OPENID, "❌ Claude Code 已退出，自动恢复失败")
                return
            pre_submit = await _capture_pane()
            # 发送 /btw：零 Escape（Escape 会中断主任务），直接输入命令。
            # 主任务 / 工具调用 / 长 Bash 照常运行，Claude PID 保持不变。
            if not await _send_btw_command(btw_question, pre_submit):
                await send_message_rest(user_openid, "⚠️ /btw 提交失败（可能被主任务过渡期吞掉），请重试")
                return
            frame = await _wait_btw_answer(pre_submit, timeout=240.0)
            btw_answer = ""
            if frame is not None:
                # 官方推荐：overlay 完成后按 c，把“当前这一条 answer”的 raw
                # Markdown 复制到 clipboard（本环境经 OSC52 进 tmux buffer）。
                # capture-pane 仅用于确认 overlay 仍开着；不再解析正文。
                for _ in range(3):
                    if not _btw_panel_is_open(await _capture_pane()):
                        break
                    btw_answer = (await _btw_copy_answer()).strip()
                    if btw_answer:
                        break
                    await asyncio.sleep(0.4)
                if btw_answer:
                    logger.info(f"[BTW] 复制 raw Markdown: {len(btw_answer)} chars")
                # 复制成功后关闭 overlay。只有确认面板仍开着才发 Escape：
                # 面板开着时 Esc 只关闭覆盖层，不会打断主任务；面板已关时
                # 发 Esc 会落到主会话，可能中断正在生成的主任务。
                if btw_answer and _btw_panel_is_open(await _capture_pane()):
                    await _tmux_send_key("Escape", pause=0.3)

        if btw_answer:
            await send_reply(user_openid, "💬 BTW\n" + btw_answer)
        else:
            await send_message_rest(user_openid, "⚠️ BTW 回答超时（240s）或未能复制完整内容，请重试")
        return

    # ── 处理图片/文件附件 ─────────────────────────────
    attachment_lines = []
    for att in attachments:
        att_url = str(att.get("url", "")).strip()
        att_type = str(att.get("content_type", "")).strip()
        att_name = str(att.get("filename", "file")).strip()
        if att_url:
            if "image" in att_type:
                attachment_lines.append(f"🖼 图片: {att_url}")
            else:
                attachment_lines.append(f"📎 文件: {att_url}")

    # --- A. /pwd（Bridge 本地处理，不经过 Claude）---
    if lower == "/pwd":
        _is_generating = False
        await send_message_rest(user_openid, f"📁 当前目录：\n{_current_cwd}")
        return

    # --- A. /ls [path]（Bridge 本地处理，不经过 Claude）---
    if lower == "/ls" or lower.startswith("/ls "):
        _is_generating = False
        arg = content.strip()[3:].strip()  # everything after "/ls"
        if arg:
            # 相对路径以当前工作目录为基准，避免被当成项目根目录解析
            target = Path(arg).expanduser()
            if not target.is_absolute():
                target = Path(_current_cwd) / target
            target = target.resolve()
        else:
            target = Path(_current_cwd)
        if not target.exists():
            await send_message_rest(user_openid, f"❌ 目录不存在: {target}")
            return
        if not target.is_dir():
            await send_message_rest(user_openid, f"❌ 不是目录: {target}")
            return
        try:
            entries = sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            await send_message_rest(user_openid, f"❌ 无权限读取目录: {target}")
            return
        # Filter hidden files, build list
        visible = [e for e in entries if not e.name.startswith(".")]
        MAX_SHOW = 50
        lines = [f"📁 {target}\n"]
        for entry in visible[:MAX_SHOW]:
            suffix = "/" if entry.is_dir() else ""
            lines.append(entry.name + suffix)
        remaining = len(visible) - MAX_SHOW
        if remaining > 0:
            lines.append(f"\n... 还有 {remaining} 项未显示")
        await send_message_rest(user_openid, "\n".join(lines))
        return

    # ── 组装发给 Claude 的消息 ────────────────────────
    if content and attachment_lines:
        claude_msg = f"{content}\n\n" + "\n".join(attachment_lines)
    elif attachment_lines:
        claude_msg = "用户发来了附件:\n" + "\n".join(attachment_lines)
    else:
        claude_msg = content

    logger.info(f"[QQ -> Claude] {claude_msg[:120]}")
    await send_to_claude(claude_msg)


async def handle_interaction(d: dict):
    """Handle QQ button callback - send keystroke directly to tmux."""
    interaction_id = d.get("id")
    if not interaction_id:
        return

    # ACK within 3 seconds
    token = await ensure_token()
    client = get_http_client()
    try:
        await client.put(
            f"{API_BASE}/interactions/{interaction_id}",
            headers={
                "Authorization": f"QQBot {token}",
                "Content-Type": "application/json",
                "User-Agent": "ClaudeCode-QQ-Bridge/3.0",
            },
            json={"code": 0},
            timeout=5.0,
        )
    except Exception as e:
        logger.error(f"[Interaction] ACK failed: {e}")

    # Parse button data
    author = d.get("author") or {}
    user_openid = d.get("user_openid") or author.get("user_openid")
    if not user_openid:
        user_openid = author.get("member_openid")
    # openid 缺失时绝不写入 .env：否则会把 MASTER_OPENID 永久污染成 "None"
    if not user_openid:
        logger.warning("[Interaction] no openid in payload, ignoring button event")
        return
    if user_openid != MASTER_OPENID:
        # Auto-bind on interaction too
        logger.warning(f"[Interaction] Unauthorized openid: {user_openid}, treating as new master")
        _save_master_openid(user_openid)

    data_block = d.get("data", {})
    button_data = data_block.get("button_data", "")

    if button_data.startswith("approve:"):
        parts = button_data.split(":")
        if len(parts) >= 3:
            keystroke = {"allow": "1", "allow_always": "2", "deny": "3"}.get(parts[2])
            if keystroke:
                # 与 C2C approve 分支保持一致：pane 内没有存活 Claude 时，
                # "1"/"2"/"3" 会被 bash 当成命令执行，绝不能发出去。
                if not _pane_has_claude():
                    logger.warning(
                        "[Interaction] claude not alive in pane — NOT sending keystroke to bash"
                    )
                    return
                proc = await asyncio.create_subprocess_exec(
                    "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", keystroke, ""
                )
                await proc.communicate()
                logger.info(f"[Interaction] Sent keystroke: {keystroke}")


async def _heartbeat_sender(ws, interval: float):
    try:
        while _running and ws and not ws.closed:
            await asyncio.sleep(interval)
            if ws and not ws.closed:
                await ws.send_json({"op": 1, "d": _last_seq})
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.debug(f"Heartbeat error: {e}")


async def event_loop(ws):
    global _session_id, _last_seq, _running, _ws, heartbeat_task, _bot_openid
    _ws = ws
    _session_id = None  # clear stale session; only READY sets it
    _last_seq = None
    heartbeat_task = asyncio.create_task(_heartbeat_sender(ws, HEARTBEAT_INTERVAL))
    identified = False
    from aiohttp import WSMsgType
    try:
        while _running and ws and not ws.closed:
            msg = await ws.receive()
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    logger.warning(f"JSON parse error: {msg.data[:100]}")
                    continue
                op = payload.get("op")
                t = payload.get("t")
                s = payload.get("s")
                d = payload.get("d")
                if isinstance(s, int) and (_last_seq is None or s > _last_seq):
                    _last_seq = s
                if op == 10:
                    d_data = d if isinstance(d, dict) else {}
                    interval_ms = d_data.get("heartbeat_interval", 30000)
                    heartbeat_interval = interval_ms / 1000.0 * 0.8
                    logger.info(f"Hello recv, heartbeat={heartbeat_interval:.1f}s")
                    # 必须用网关下发的 interval 重建心跳 task（旧 task 已用写死的
                    # HEARTBEAT_INTERVAL 启动，算出的值之前被丢弃了）。先取消旧的
                    # 避免多个心跳 task 并发；重连后每次 Hello 都会重新走到这里。
                    if heartbeat_task and not heartbeat_task.done():
                        heartbeat_task.cancel()
                    heartbeat_task = asyncio.create_task(
                        _heartbeat_sender(ws, heartbeat_interval)
                    )
                    if not identified:
                        await send_identify(ws)
                    continue
                if op == 0 and t:
                    logger.info(f"[WS Dispatch] event_type={t}")
                    if t == "READY" and isinstance(d, dict):
                        _session_id = d.get("session_id")
                        user = d.get("user") if isinstance(d.get("user"), dict) else {}
                        _bot_openid = str(user.get("id", ""))
                        identified = True
                        logger.info(f"READY, session_id={_session_id}, bot_openid={_bot_openid}")
                    elif t == "RESUMED":
                        identified = True
                        logger.info("Session resumed")
                    elif t == "C2C_MESSAGE_CREATE":
                        task = asyncio.create_task(handle_c2c_message(d))
                        task.add_done_callback(
                            lambda t: logger.error(f"[Task] C2C message handler failed: {t.exception()}") if t.exception() else None
                        )
                    elif t == "INTERACTION_CREATE":
                        task = asyncio.create_task(handle_interaction(d))
                        task.add_done_callback(
                            lambda t: logger.error(f"[Task] Interaction handler failed: {t.exception()}") if t.exception() else None
                        )
                    continue
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                logger.warning(f"WS close received (type={msg.type!r})")
                break
            elif msg.type == WSMsgType.ERROR:
                logger.error(f"WS error received: {ws.exception()}")
                break
            # PING/PONG 由 aiohttp 自动响应，无需处理
    except Exception as e:
        logger.error(f"Event loop error: {e}")
    finally:
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


def _detect_proxy_config() -> tuple:
    """检测代理环境变量，返回 (trust_env, 日志描述)。

    trust_env=True 让 aiohttp 自动读取标准代理变量（HTTPS_PROXY / https_proxy /
    HTTP_PROXY / http_proxy / ALL_PROXY / all_proxy）；不硬编码任何本地代理。
    遇到 SOCKS 时返回 False——aiohttp 内置代理仅支持 http/https，SOCKS 不假装
    支持，明确回退直连。描述已脱敏，不含可能的账号密码。
    """
    proxy_env = next(
        (
            v
            for v in (
                os.environ.get("HTTPS_PROXY"),
                os.environ.get("https_proxy"),
                os.environ.get("HTTP_PROXY"),
                os.environ.get("http_proxy"),
                os.environ.get("ALL_PROXY"),
                os.environ.get("all_proxy"),
            )
            if v
        ),
        None,
    )
    if not proxy_env:
        return True, "未检测到代理环境变量，使用直连"
    scheme = proxy_env.split("://", 1)[0].lower()
    # 脱敏：只显示 host:port，不显示可能含账号密码的完整 URL
    masked = proxy_env.rsplit("@", 1)[-1]
    if scheme in ("socks", "socks4", "socks5", "socks5h"):
        return False, (
            f"检测到 SOCKS 代理({scheme}://{masked})，aiohttp 内置不支持 SOCKS，"
            "本轮将直连。如需 SOCKS，请安装 aiohttp_socks 后自行接入。"
        )
    return True, f"检测到代理环境变量: {scheme}://{masked}"


async def main():
    global _running
    _running = True
    logger.info(f"Starting Claude Code QQ Bridge {_get_version()}...")

    # 1. Start Claude Code in tmux
    await start_claude_in_tmux()
    if not _claude_session_id:
        logger.warning("No Claude Code session found, retrying in 10s...")
        await asyncio.sleep(10)
        if not await _ensure_claude_alive():
            logger.error(
                "Bridge started but no live Claude session could be bound. "
                "Will auto-recover on next QQ message."
            )

    # 2. Start background polling
    asyncio.create_task(periodic_poll())

    # 3. Connect QQ Bot gateway
    try:
        gateway_url = await get_gateway_url()
        logger.info(f"Gateway URL: {gateway_url}")
    except Exception as e:
        logger.error(f"Failed to get gateway: {e}")
        sys.exit(1)

    import aiohttp

    # ── 代理兼容 ─────────────────────────────────────────────────────────
    # trust_env=True 让 aiohttp 自动读取标准代理环境变量，见 _detect_proxy_config()
    trust_env, proxy_note = _detect_proxy_config()
    if proxy_note.startswith("检测到 SOCKS"):
        logger.warning(proxy_note)
    else:
        logger.info(proxy_note)

    retry_index = 0
    while _running:
        try:
            async with aiohttp.ClientSession(trust_env=trust_env) as session:
                async with session.ws_connect(
                    gateway_url,
                    timeout=aiohttp.ClientTimeout(sock_connect=CONNECT_TIMEOUT),
                ) as ws:
                    logger.info("WS connected")
                    retry_index = 0  # reset backoff on successful connect
                    await event_loop(ws)
        except asyncio.CancelledError:
            break
        except Exception as e:
            if _running:
                logger.error(f"WS error: {e}")
        # Delay before reconnect (applies to both normal-exit and exception paths)
        if _running:
            delay = RECONNECT_BACKOFF[min(retry_index, len(RECONNECT_BACKOFF) - 1)]
            logger.info(f"Reconnecting in {delay}s (retry={retry_index})")
            retry_index += 1
            await asyncio.sleep(delay)
    logger.info("Bridge stopped")

def _get_version() -> str:
    """版本号统一从已安装 package metadata 读取（由根 VERSION 同步而来）。"""
    try:
        from importlib.metadata import version
        return version("claude-code-qq-bridge")
    except Exception:
        return "0.0.0"


def cli() -> int:
    """CLI 入口：处理 --init / --version 后运行主桥接"""
    import sys

    if '--init' in sys.argv or (len(sys.argv) > 1 and sys.argv[1] == '--init'):
        print('TODO: --init not yet implemented')
        return 0

    if '--version' in sys.argv or '-V' in sys.argv:
        print(_get_version())
        return 0

    if '--help' in sys.argv or '-h' in sys.argv:
        print('用法:')
        print('  claude-code-qq-bridge            启动桥接服务')
        print('  claude-code-qq-bridge --init     交互式配置（首次使用）')
        print('  claude-code-qq-bridge --version  显示版本号')
        print('  claude-code-qq-bridge --help     显示帮助')
        return 0

    # 检查 .env
    env_found = any(
        __import__('pathlib').Path(p).exists()
        for p in ['.env', str(__import__('pathlib').Path(__file__).parent / '.env'), str(__import__('pathlib').Path.home() / 'AI-Bridge-QQrobot-claude' / '.env')]
    )
    if not env_found:
        print('⚠️  未找到 .env 配置文件！')
        print('   请先运行: claude-code-qq-bridge --init')
        print('   或手动创建 .env 文件（参考 .env.example）')
        return 1

    if not APP_ID or not CLIENT_SECRET:
        logger.error('Missing config: APP_ID, CLIENT_SECRET')
        return 1
    if not MASTER_OPENID:
        logger.warning('MASTER_OPENID not set, will auto-bind on first C2C message')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Interrupted by user')
    return 0
