#!/usr/bin/env python3
"""
claude-code-qq-bridge.py v3.0 - Claude Code QQ Bridge

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
import sys
import time
import uuid
import logging
from typing import Optional, Dict
from pathlib import Path

# ================= .env 配置加载 =================
def load_env():
    """极简 .env 解析，零依赖"""
    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path("/root/claude-code-qq-bridge/.env"),
    ]
    for p in candidates:
        if p.exists():
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
CLAUDE_HOME = str(Path.home() / ".claude")
CLAUDE_PROJECT = "-root"
API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
GATEWAY_URL_PATH = "/gateway"
CONNECT_TIMEOUT = 20
RECONNECT_BACKOFF = [2, 5, 10, 30, 60]
HEARTBEAT_INTERVAL = 15.0

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_DIR / "claude-code-qq-bridge.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("claude_code_bridge")

# === State: JSONL 文件跟踪（AGY 风格，不依赖 session UUID） ===
_log_path: Optional[str] = None          # 当前绑定的 JSONL 文件路径
_log_position: int = 0                   # 上次读取的文件位置（字节 offset）
_log_last_mtime: float = 0.0             # 上次读取时的文件 mtime
_jsonl_watermark: int = 0                # 兼容旧代码的 legacy watermark（不再更新）

_access_token: Optional[str] = None
_token_expires_at: float = 0.0
_ws = None
_http_client = None
_running = False
_last_seq: Optional[int] = None
_last_msg_id: Optional[str] = None
_last_typing_sent_time = 0.0  # 记录上次发送"正在输入"通知的时间戳
_is_generating = False  # 是否处于等待 AI 响应的生成状态
_generating_since = 0.0  # 进入生成状态的时间，超时自动 reset
_bot_openid: str = ""

# === 异步群聊缓存与动态路由 ===
GROUP_CHAT_BUFFER: list = []
LAST_MESSAGE_SOURCE: dict = {"type": "c2c", "openid": "", "reply_to": None}
_processing: bool = False  # 群聊处理锁定，防止并发
_pending_group: Optional[dict] = None  # 待回复的群消息来源（openid + msg_id）


def find_latest_jsonl() -> Optional[str]:
    """AGY 风格：扫描项目目录，找最新修改的 JSONL 文件。"""
    project_dir = Path(CLAUDE_HOME) / "projects" / CLAUDE_PROJECT
    if not project_dir.exists():
        return None
    best_path = None
    best_mtime = 0.0
    for f in project_dir.glob("*.jsonl"):
        try:
            mtime = f.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_path = str(f)
        except OSError:
            continue
    return best_path


def refresh_log_path():
    """绑定到最新的 JSONL 文件。如果文件变了，直接跳到末尾，不重读旧消息。"""
    global _log_path, _log_position, _log_last_mtime, _jsonl_watermark
    latest = find_latest_jsonl()
    if not latest:
        logger.warning("[Log] No JSONL files found, waiting...")
        return False
    if latest != _log_path:
        # 切换到了新文件 → 跳到末尾，不重放旧消息
        _log_path = latest
        try:
            _log_position = Path(latest).stat().st_size
        except OSError:
            _log_position = 0
        _log_last_mtime = time.time()
        _jsonl_watermark = 0
        logger.info(f"[Log] Bound to: {latest} (skip to end, pos={_log_position})")
    else:
        # 同一文件，更新 mtime
        try:
            _log_last_mtime = Path(latest).stat().st_mtime
        except OSError:
            pass
    return True


def check_log_rotation() -> bool:
    """检查是否有更新的 JSONL 文件出现（比如 restart 后新建的 session），
    有则自动切换，不重放旧消息。返回 True 表示可以继续轮询，False 暂时没有可用文件。"""
    global _log_path, _log_position, _log_last_mtime, _jsonl_watermark
    latest = find_latest_jsonl()
    if not latest:
        return False
    if latest != _log_path:
        logger.info(f"[Log] Newer log detected: {latest}, switching...")
        _log_path = latest
        try:
            _log_position = Path(latest).stat().st_size
        except OSError:
            _log_position = 0
        _log_last_mtime = time.time()
        _jsonl_watermark = 0
        logger.info(f"[Log] Switched to: {latest} (skip to end, pos={_log_position})")
    return True


def get_session_file_from_log() -> Optional[Path]:
    """从当前 JSONL 文件推导 sessionId，再在 sessions 目录找对应的 session 文件。"""
    if not _log_path:
        return None
    log_name = Path(_log_path).stem  # session UUID
    sessions_dir = Path(CLAUDE_HOME) / "sessions"
    if not sessions_dir.exists():
        return None
    for sf in sessions_dir.glob("*.json"):
        try:
            with open(sf) as f:
                data = json.load(f)
            if data.get("sessionId") == log_name:
                return sf
        except (json.JSONDecodeError, IOError):
            continue
    return None


def get_session_status() -> Optional[Dict]:
    """Read session file for waitingFor field."""
    session_file = get_session_file_from_log()
    if not session_file or not session_file.exists():
        return None
    try:
        with open(session_file) as f:
            data = json.load(f)
        return {
            "status": data.get("status"),
            "waitingFor": data.get("waitingFor"),
        }
    except (json.JSONDecodeError, IOError):
        return None


async def send_to_claude(message: str):
    """Send message to Claude Code via tmux."""
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
    logger.info(f"[Bridge -> Claude] {message[:100]}")





async def start_claude_in_tmux():
    """Start Claude Code in tmux. Always kills any existing Claude first."""
    # Ensure tmux session exists
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

        # Clear any stale input on shell line before starting Claude
        for key in ["C-c", "C-c"]:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
            )
            await proc.communicate()
            await asyncio.sleep(0.2)
        # Start fresh Claude
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{TMUX_SESSION}:",
            "cd /root && script -q -c 'claude --permission-mode auto' /dev/null", "Enter"
        )
        await proc.communicate()
        # Wait for trust prompt, then press "1" to confirm
        await asyncio.sleep(5)
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "1", ""
        )
        await proc.communicate()
        await asyncio.sleep(3)

    # 刷新绑定到最新的 JSONL 文件
    refresh_log_path()


async def stop_claude_in_tmux():
    """Stop Claude Code with Ctrl+C."""
    for key in ["C-c", "Enter", "C-c"]:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
        )
        await proc.communicate()
        await asyncio.sleep(0.3)
    logger.info("Sent Ctrl+C to Claude")


async def restart_claude_in_tmux():
    """Restart Claude Code: kill old tmux session, start fresh (AGY style)."""
    global _log_path, _log_position, _log_last_mtime, _jsonl_watermark
    logger.info("Restarting Claude Code...")

    # 1. 强杀整个 tmux 会话（AGY 方案，clean state）
    proc = await asyncio.create_subprocess_shell(
        f"tmux kill-session -t {TMUX_SESSION} 2>/dev/null || true"
    )
    await proc.communicate()
    await asyncio.sleep(0.5)

    # 2. 重建 tmux 会话
    proc = await asyncio.create_subprocess_exec(
        "tmux", "new-session", "-d", "-s", TMUX_SESSION
    )
    await proc.communicate()
    await asyncio.sleep(1)

    # 3. 清除可能残留的输入
    for key in ["C-c", "C-c"]:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
        )
        await proc.communicate()
        await asyncio.sleep(0.2)

    # 4. 启动全新 Claude
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:",
        "cd /root && script -q -c 'claude --permission-mode auto' /dev/null", "Enter"
    )
    await proc.communicate()
    await asyncio.sleep(5)
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "1", ""
    )
    await proc.communicate()

    # 4. 记录旧文件路径以便检测新文件产生
    old_log = _log_path
    for attempt in range(15):  # up to ~30 seconds
        await asyncio.sleep(2)
        latest = find_latest_jsonl()
        if latest and latest != old_log:
            _log_path = latest
            try:
                _log_position = Path(latest).stat().st_size
            except OSError:
                _log_position = 0
            _log_last_mtime = time.time()
            logger.info(f"[Restart] New log detected: {latest}")
            break
    else:
        logger.warning(f"[Restart] Timed out waiting for new log, staying on {_log_path}")

    logger.info("Claude Code restarted")


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


def _next_msg_seq(msg_id: str = 'default') -> int:
    time_part = int(time.time()) % 100000000
    rnd = int(uuid.uuid4().hex[:4], 16)
    return (time_part ^ rnd) % 65536


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
    """发送"正在输入"通知"""
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


async def send_message_rest(user_openid: str, content: str, *, keyboard: bool = False) -> bool:
    """Send message to QQ user. If keyboard=True, append approval buttons."""
    token = await ensure_token()
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "User-Agent": "ClaudeCode-QQ-Bridge/3.0",
    }
    msg_seq = _next_msg_seq(user_openid)
    display_content = content[:1500] + "\n\n... (truncated)" if len(content) > 1500 else content
    body = {"markdown": {"content": display_content}, "msg_type": 2, "msg_seq": msg_seq}

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


async def send_group_message_rest(group_openid: str, content: str, reply_to: Optional[str] = None) -> bool:
    """给指定群聊发送消息（AGY 风格，群 API 不支持 markdown）"""
    token = await ensure_token()
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "User-Agent": "ClaudeCode-QQ-Bridge/3.0",
    }
    display_content = content[:1500] + "\n\n... (truncated)" if len(content) > 1500 else content
    body = {"content": display_content, "msg_type": 0, "msg_seq": _next_msg_seq(group_openid)}
    try:
        resp = await client.post(f"{API_BASE}/v2/groups/{group_openid}/messages", headers=headers, json=body, timeout=30.0)
        if resp.status_code >= 400:
            logger.error(f"Send group failed [{resp.status_code}]: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.error(f"Send group exception: {e}")
        return False


# ================= 图片消息发送（media msg_type 7） =================

async def upload_image_to_qq(url: str, token: str, openid: str, is_group: bool = False) -> Optional[str]:
    """上传图片 URL 到 QQ 服务器，返回 file_info。"""
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    }
    body = {"file_type": 1, "url": url}
    endpoint = f"{API_BASE}/v2/groups/{openid}/files" if is_group else f"{API_BASE}/v2/users/{openid}/files"
    try:
        resp = await client.post(endpoint, headers=headers, json=body, timeout=30.0)
        if resp.status_code >= 400:
            logger.error(f"[UploadImage] failed [{resp.status_code}]: {resp.text[:200]}")
            return None
        data = resp.json()
        fi = data.get("file_info")
        logger.info(f"[UploadImage] success{' (group)' if is_group else ''}, file_info_len={len(fi) if fi else 0}")
        return fi
    except Exception as e:
        logger.error(f"[UploadImage] exception: {e}")
        return None


async def send_image_to_user(url: str, openid: str) -> bool:
    """上传图片 URL 并发送媒体消息给 C2C 用户。"""
    token = await ensure_token()
    file_info = await upload_image_to_qq(url, token, openid=openid)
    if not file_info:
        return False
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    }
    body = {
        "msg_type": 7,
        "media": {"file_info": file_info},
        "msg_seq": _next_msg_seq(openid),
    }
    try:
        resp = await client.post(f"{API_BASE}/v2/users/{openid}/messages", headers=headers, json=body, timeout=30.0)
        if resp.status_code >= 400:
            logger.error(f"[SendImage] C2C failed [{resp.status_code}]: {resp.text[:200]}")
            return False
        logger.info(f"[SendImage] C2C success")
        return True
    except Exception as e:
        logger.error(f"[SendImage] C2C exception: {e}")
        return False


async def send_image_to_group(url: str, group_openid: str, reply_to: Optional[str] = None) -> bool:
    """上传图片 URL 并发送媒体消息给群聊。"""
    token = await ensure_token()
    file_info = await upload_image_to_qq(url, token, openid=group_openid, is_group=True)
    if not file_info:
        return False
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    }
    body = {
        "msg_type": 7,
        "media": {"file_info": file_info},
        "msg_seq": _next_msg_seq(group_openid),
    }
    if reply_to:
        body["msg_id"] = reply_to
    try:
        resp = await client.post(f"{API_BASE}/v2/groups/{group_openid}/messages", headers=headers, json=body, timeout=30.0)
        if resp.status_code >= 400:
            logger.error(f"[SendImage] Group failed [{resp.status_code}]: {resp.text[:200]}")
            return False
        logger.info(f"[SendImage] Group success")
        return True
    except Exception as e:
        logger.error(f"[SendImage] Group exception: {e}")
        return False


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
    global _jsonl_watermark, _is_generating, _last_typing_sent_time, _generating_since, _log_position, LAST_MESSAGE_SOURCE, _pending_group, _processing
    while True:
        # 触发/续杯"正在输入中"的顶部状态（仅 C2C，群聊不支持）
        now = time.time()
        if _is_generating and _last_msg_id and (now - _last_typing_sent_time > 2.5) and LAST_MESSAGE_SOURCE.get("type") != "group":
            asyncio.create_task(send_input_notify(MASTER_OPENID, _last_msg_id))
            _last_typing_sent_time = now

        # 超时自动重置"正在输入"状态（防止卡死超过 5 分钟）
        if _is_generating and _generating_since > 0 and (now - _generating_since > 300):
            logger.warning(f"[Poll] _is_generating timeout ({int(now - _generating_since)}s), auto-reset")
            _is_generating = False
            _generating_since = 0.0

        # 超时自动重置群聊处理锁（防止卡死超过 120 秒），但保留 _pending_group 等回复
        if _processing and _generating_since > 0 and (now - _generating_since > 120):
            logger.warning(f"[Poll] _processing timeout ({int(now - _generating_since)}s), auto-reset")
            _processing = False

        await asyncio.sleep(3)
        try:
            # 0. Check for log rotation (newer JSONL file appeared)
            if not check_log_rotation():
                continue

            # 1. Read JSONL for new assistant replies (BEFORE approval check)
            new_texts = []
            if _log_path and Path(_log_path).exists():
                with open(_log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(_log_position)
                    new_data = f.read()
                    _log_position = f.tell()
                if new_data:
                    for line in new_data.splitlines():
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

            # 2. Check approval status (session file)
            status = get_session_status()
            approval_pending = status and status.get("waitingFor") == "permission prompt"
            is_idle = status and status.get("status") in ("idle", "shell")

            if is_idle:
                _is_generating = False
                _generating_since = 0.0
                if _processing:
                    _processing = False
                    # 注意：不清理 _pending_group，等回复到了再发

            if approval_pending:
                _is_generating = False  # 进入等待授权，关闭输入状态
                _generating_since = 0.0
                # Send text first (as normal message), then approval button (separate message)
                if new_texts:
                    reply = "\n\n".join(new_texts)
                    logger.info(f"[Poll -> QQ Text] {reply[:80]}")
                    await send_message_rest(MASTER_OPENID, reply[:1500])
                    await asyncio.sleep(0.3)  # small gap to avoid QQ rate limit

                logger.info("[Poll] Approval detected, sending QQ button")
                # 群聊可发审批按钮吗？暂只私聊发
                await send_message_rest(MASTER_OPENID, "🔐 **Claude Code 需要您的确认**", keyboard=True)

                # Block until user handles approval
                await _wait_for_approval()
                logger.info("[Poll] Approval handled, resumed polling")
                continue

            # 3. No approval pending — just push text if any
            if new_texts:
                reply = "\n\n".join(new_texts)

                # 检查是否有图片发送标记 [SEND_IMAGE]url
                import re as _re
                img_match = _re.search(r'\[SEND_IMAGE\](\S+)', reply)
                img_url = img_match.group(1) if img_match else None
                text_reply = _re.sub(r'\s*\[SEND_IMAGE\]\S+\s*', '\n', reply).strip() if img_url else reply

                # 优先发送文本（如有）
                send_text = text_reply[:1500] if text_reply else None

                # 优先检查是否有待回复的群消息
                if _pending_group:
                    pg = _pending_group
                    _pending_group = None
                    _processing = False
                    if send_text:
                        logger.info(f"[Poll -> group] {send_text[:100]}")
                        await send_group_message_rest(pg["openid"], send_text, reply_to=pg["msg_id"])
                    if img_url:
                        await asyncio.sleep(0.5)
                        logger.info(f"[Poll -> group image] {img_url[:60]}")
                        await send_image_to_group(img_url, pg["openid"], reply_to=pg["msg_id"])
                else:
                    target_type = LAST_MESSAGE_SOURCE.get("type", "c2c")
                    logger.info(f"[Poll -> {target_type}] {send_text[:100] if send_text else '(image only)'}")
                    target = LAST_MESSAGE_SOURCE
                    if target["type"] == "group":
                        if send_text:
                            await send_group_message_rest(target["openid"], send_text, reply_to=target.get("reply_to"))
                        if img_url:
                            await asyncio.sleep(0.5)
                            await send_image_to_group(img_url, target["openid"], reply_to=target.get("reply_to"))
                    else:
                        dest = target["openid"] or MASTER_OPENID
                        if dest:
                            if send_text:
                                await send_message_rest(dest, send_text)
                            if img_url:
                                await asyncio.sleep(0.5)
                                await send_image_to_user(img_url, dest)
        except Exception as e:
            logger.error(f"[Poll] error: {e}")


def _save_master_openid(openid: str):
    """Persist MASTER_OPENID to .env file."""
    global MASTER_OPENID
    if openid == MASTER_OPENID:
        return
    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path("/root/claude-code-qq-bridge/.env"),
    ]
    for p in candidates:
        if p.exists():
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
    global _last_msg_id, _bot_openid, _is_generating, LAST_MESSAGE_SOURCE
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
    # 记录来源为 C2C 私聊
    LAST_MESSAGE_SOURCE = {"type": "c2c", "openid": user_openid, "reply_to": None}
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
                logger.info(f"[Approval] Sending keystroke: {keystroke}")
                proc = await asyncio.create_subprocess_exec(
                    "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", keystroke, ""
                )
                await proc.communicate()
        return

    # Commands
    if content.strip().lower() in ["/new", "/reset", "/qingkong", "/xin duihua"]:
        _is_generating = False
        logger.info("[Recv] New session command")
        await restart_claude_in_tmux()
        await send_message_rest(user_openid, "Session restarted.")
        return
    if content.strip().lower() in ["/stop", "/tingzhi", "/kill"]:
        _is_generating = False
        logger.info("[Recv] Stop command")
        await stop_claude_in_tmux()
        await send_message_rest(user_openid, "⛔ Interrupted.")
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

    # ── 组装发给 Claude 的消息 ────────────────────────
    if content and attachment_lines:
        claude_msg = f"{content}\n\n" + "\n".join(attachment_lines)
    elif attachment_lines:
        claude_msg = "用户发来了附件:\n" + "\n".join(attachment_lines)
    else:
        claude_msg = content

    logger.info(f"[QQ -> Claude] {claude_msg[:120]}")
    await send_to_claude(claude_msg)


async def handle_group_message(d: dict, event_type: str):
    """Handle group message. 不 @ 时缓存上下文，@ 时带上下文处理（AGY 风格）"""
    global _last_msg_id, _bot_openid, LAST_MESSAGE_SOURCE, GROUP_CHAT_BUFFER, _is_generating, _generating_since, _processing, _pending_group

    msg_id = str(d.get("id", ""))
    if not msg_id or is_duplicate(msg_id):
        return

    content = str(d.get("content", "")).strip()
    attachments = d.get("attachments") or []
    for att in attachments:
        url = att.get("url")
        if url:
            name = att.get("filename") or att.get("name") or "file"
            content += f"\n\n[附件({name}): {url}]"

    content = content.strip()
    group_openid = str(d.get("group_openid", ""))
    author = d.get("author") if isinstance(d.get("author"), dict) else {}
    member_openid = str(author.get("member_openid", ""))

    if not group_openid or not content:
        return

    sender_name = author.get("nickname") or author.get("username")
    if not sender_name:
        sender_name = f"user_{member_openid[-6:]}" if member_openid else "User"

    # 过滤 @ 机器人的前缀
    clean_content = content
    if _bot_openid:
        clean_content = clean_content.replace(f"<@!{_bot_openid}>", "").strip()

    msg_line = f"[{sender_name}] {clean_content}"

    # 判断是否被 @
    is_mentioned = False
    if event_type == "GROUP_AT_MESSAGE_CREATE":
        is_mentioned = True
    else:
        mentions = d.get("mentions") or []
        for m in mentions:
            if m.get("is_you") is True:
                is_mentioned = True
                break
            mid = m.get("member_openid") or m.get("id") or m.get("user_openid") or ""
            if _bot_openid and str(mid) == str(_bot_openid):
                is_mentioned = True
                break

    if not is_mentioned:
        # 没被 @ 时默默记录到缓冲中
        GROUP_CHAT_BUFFER.append(msg_line)
        if len(GROUP_CHAT_BUFFER) > 100:
            GROUP_CHAT_BUFFER.pop(0)
        logger.info(f"[Group Buffer] From {sender_name}: {clean_content[:50]}")
        return

    _last_msg_id = msg_id
    _is_generating = True
    _generating_since = time.time()
    logger.info(f"[Group Recv AT] From {sender_name}: {clean_content[:100]}")

    # 动态更新最后来源（备用，群聊回复直接用同步模式发）
    LAST_MESSAGE_SOURCE = {"type": "group", "openid": group_openid, "reply_to": msg_id}

    # 判断发送人是否是主人
    is_master = (member_openid == MASTER_OPENID)

    if is_master and clean_content.lower() in ["/new", "/reset", "/qingkong", "/xin duihua"]:
        _is_generating = False
        logger.info("[Group Recv] Reset command")
        GROUP_CHAT_BUFFER.clear()
        await restart_claude_in_tmux()
        await send_group_message_rest(group_openid, "✅ 会话已重置。", reply_to=msg_id)
        return

    if is_master and clean_content.lower() in ["/stop", "/tingzhi", "/kill"]:
        _is_generating = False
        logger.info("[Group Recv] Stop command")
        await stop_claude_in_tmux()
        await send_group_message_rest(group_openid, "⛔ 已中断。", reply_to=msg_id)
        return

    # 群聊处理锁定，防止并发
    if _processing:
        logger.info("[Group Recv] Already processing, queuing...")
        # 非 @ 消息缓存，@ 消息时再处理
        GROUP_CHAT_BUFFER.append(msg_line)
        if len(GROUP_CHAT_BUFFER) > 100:
            GROUP_CHAT_BUFFER.pop(0)
        await send_group_message_rest(group_openid, "⏳ 正在处理上一条消息，请稍候...", reply_to=msg_id)
        return

    # 拼接群聊历史上下文
    full_payload = ""
    if GROUP_CHAT_BUFFER:
        full_payload += "以下是之前的群聊讨论上下文：\n"
        full_payload += "\n".join(GROUP_CHAT_BUFFER)
        full_payload += "\n\n请针对上述讨论，回答我当前的提问：\n"

    full_payload += f"[{sender_name}] {clean_content}"

    # 消费后立即清空缓存
    GROUP_CHAT_BUFFER.clear()

    # 群聊走 tmux + 轮询（跟私聊一样），用 _pending_group 标记回复目标
    _processing = True
    _pending_group = {"openid": group_openid, "msg_id": msg_id}
    logger.info(f"[Group -> Claude] {full_payload[:80]}")
    await send_to_claude(full_payload)


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
    if user_openid and user_openid != MASTER_OPENID:
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
    global _session_id, _last_seq, _running, _ws, heartbeat_task
    _ws = ws
    _session_id = None  # clear stale session; only READY sets it
    _last_seq = None
    heartbeat_task = asyncio.create_task(_heartbeat_sender(ws, HEARTBEAT_INTERVAL))
    identified = False
    try:
        while _running and ws and not ws.closed:
            msg = await ws.receive()
            if msg.type == 1:
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
                        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                    elif t in {"GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"}:
                        task = asyncio.create_task(handle_group_message(d, t))
                        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                    elif t == "INTERACTION_CREATE":
                        task = asyncio.create_task(handle_interaction(d))
                        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                    continue
            elif msg.type == 9:
                logger.warning("WS close received")
                break
    except Exception as e:
        logger.error(f"Event loop error: {e}")
    finally:
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


async def main():
    global _running
    _running = True
    logger.info("Starting Claude Code QQ Bridge v3.0...")

    # 1. Start Claude Code in tmux
    await start_claude_in_tmux()
    # refresh_log_path() is called inside start_claude_in_tmux()

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
    retry_index = 0
    while _running:
        try:
            async with aiohttp.ClientSession() as session:
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


if __name__ == "__main__":
    if not APP_ID or not CLIENT_SECRET:
        logger.error("Missing config: APP_ID, CLIENT_SECRET")
        sys.exit(1)
    if not MASTER_OPENID:
        logger.warning("MASTER_OPENID not set, will auto-bind on first C2C message")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
