#!/usr/bin/env python3
"""
codex-qq-bridge.py v1.0 — Codex QQ Bridge

架构:
  QQ → WS网关 → bridge → tmux send-keys → Codex (interactive mode)
     ↑                                    ↓
     +—— session JSONL 轮询 → push reply

原则:
  - 复用老桥（Claude/AGY）经过验证的 QQ WS 网关代码
  - 只用 JSONL 轮询，不用 capture-pane（AGY 踩过坑）
  - MASTER_OPENID 自动绑定
  - 无审批按钮，Codex 用 on-request 模式自己判断
"""

import asyncio
import json
import os
import sys
import time
import uuid
import logging
from typing import Optional, Dict, List
from pathlib import Path

# ================= .env 配置加载 =================
def load_env():
    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
        Path("/root/codex-qq-bridge/.env"),
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
                        # .env must override inherited env vars, otherwise the
                        # bridge can silently keep stale credentials.
                        os.environ[key.strip()] = val.strip().strip('"').strip("'")
                break
            except Exception:
                pass

load_env()

# Avoid inheriting tmux client variables from the caller environment.
os.environ.pop("TMUX", None)
os.environ.pop("TMUX_PANE", None)

# ================= 配置区 =================
APP_ID = os.environ.get("APP_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")
MASTER_OPENID = os.environ.get("MASTER_OPENID", "")
TMUX_SESSION = os.environ.get("TMUX_SESSION", "codex")
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
CODEX_SESSION_DIR = CODEX_HOME / "sessions"

API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
GATEWAY_URL_PATH = "/gateway"
CONNECT_TIMEOUT = 20
RECONNECT_BACKOFF = [2, 5, 10, 30, 60]
HEARTBEAT_INTERVAL = 15.0

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_DIR / "codex-qq-bridge.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("codex_bridge")

# ================= 状态 =================
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
_poll_task: Optional[asyncio.Task] = None

# === JSONL 轮询状态 ===
_jsonl_path: Optional[Path] = None
_jsonl_watermark: int = 0      # 当前文件已读行数
_last_sent_ts: str = ""        # 最后发送的消息时间戳，防历史刷屏

_seen_message_ids: Dict[str, float] = {}
_recent_reply_texts: Dict[str, float] = {}
_recent_inbound_texts: Dict[str, float] = {}


# ================= 工具函数 =================

def is_duplicate(msg_id: str) -> bool:
    now = time.time()
    if msg_id in _seen_message_ids and now - _seen_message_ids[msg_id] < 300:
        return True
    _seen_message_ids[msg_id] = now
    if len(_seen_message_ids) > 1000:
        for k in list(_seen_message_ids.keys()):
            if now - _seen_message_ids[k] > 600:
                del _seen_message_ids[k]
    return False


def is_duplicate_reply(text: str, window_seconds: float = 5.0) -> bool:
    """Skip near-immediate duplicate assistant replies from parallel JSONL event shapes."""
    now = time.time()
    key = " ".join(text.split())
    if not key:
        return False
    last = _recent_reply_texts.get(key)
    _recent_reply_texts[key] = now
    if len(_recent_reply_texts) > 1000:
        for k in list(_recent_reply_texts.keys()):
            if now - _recent_reply_texts[k] > 600:
                del _recent_reply_texts[k]
    return last is not None and (now - last) < window_seconds


def is_duplicate_inbound(user_openid: str, content: str, window_seconds: float = 3.0) -> bool:
    """Skip near-immediate duplicate inbound deliveries from QQ gateway."""
    now = time.time()
    key = f"{user_openid}\n{' '.join(content.split())}"
    if not key.strip():
        return False
    last = _recent_inbound_texts.get(key)
    _recent_inbound_texts[key] = now
    if len(_recent_inbound_texts) > 1000:
        for k in list(_recent_inbound_texts.keys()):
            if now - _recent_inbound_texts[k] > 600:
                del _recent_inbound_texts[k]
    return last is not None and (now - last) < window_seconds


def _next_msg_seq() -> int:
    time_part = int(time.time()) % 100000000
    rnd = int(uuid.uuid4().hex[:4], 16)
    return (time_part ^ rnd) % 65536


def get_http_client():
    global _http_client
    if _http_client is None:
        import httpx
        _http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    return _http_client


# ================= Codex 会话检测 =================

def find_latest_session_jsonl() -> Optional[Path]:
    """按文件名时间戳找最新的 Codex session JSONL 文件（不用 mtime，防重启瞬间误判）。"""
    if not CODEX_SESSION_DIR.exists():
        return None
    files = sorted(CODEX_SESSION_DIR.rglob("rollout-*.jsonl"),
                   key=lambda p: p.name, reverse=True)
    return files[0] if files else None


def count_lines(path: Path) -> int:
    """快速统计文件行数。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except (IOError, OSError):
        return 0


def translate_structured_line(obj: dict) -> Optional[str]:
    """Strictly translate known JSONL structured fields to QQ text.
    
    Only handles well-known Codex JSONL structure:
      response_item / message (assistant)   -> final reply text
      event_msg    / agent_message          -> legacy compat

    Skips (intermediate, NOT pushed to QQ):
      response_item / function_call        -> tool call (intermediate)
      response_item / function_call_output -> tool result (intermediate)
      response_item / reasoning             -> thinking (intermediate)
      event_msg    / agent_message          -> legacy compat

    No guessing. No regex. No heuristic parsing.
    Unknown types -> returns None (silently skipped).
    """
    if not isinstance(obj, dict):
        return None

    msg_type = obj.get("type", "")

    # --- response_item ---
    if msg_type == "response_item":
        payload = obj.get("payload", {})
        if not isinstance(payload, dict):
            return None
        ptype = payload.get("type", "")

        if ptype == "function_call":
            return None

        # function_call_output
        if ptype == "function_call_output":
            return None

        # reasoning → skip (intermediate)
        if ptype == "reasoning":
            return None

        # message: only assistant role = final reply
        if ptype == "message" and payload.get("role") == "assistant":
            content = payload.get("content", [])
            texts = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        t = block.get("text", "").strip()
                        if t:
                            texts.append(t)
            if texts:
                final = "\n\n".join(texts)
                if len(final) > 1500:
                    final = final[:1500] + "\n...(truncated)"
                return final
            return None

        # other response_item types -> skip
        return None

    # --- event_msg (backup path for agent_message) ---
    if msg_type == "event_msg":
        _payload = obj.get("payload")
        if isinstance(_payload, dict) and _payload.get("type") == "agent_message":
            msg = _payload.get("message", "")
            if isinstance(msg, str) and msg.strip():
                text = msg.strip()
                if len(text) > 1500:
                    text = text[:1500] + "\n...(truncated)"
                return text
        return None

    # unknown type -> skip
    return None


def refresh_session_jsonl() -> bool:
    """刷新当前追踪的 JSONL 文件。检测是否有新会话文件生成。"""
    global _jsonl_path, _jsonl_watermark, _last_sent_ts

    latest = find_latest_session_jsonl()

    if not latest:
        return False

    # 如果是新文件（路径变了），重置水位
    if not _jsonl_path or latest != _jsonl_path:
        _jsonl_path = latest
        _jsonl_watermark = count_lines(latest)
        _last_sent_ts = ""
        logger.info(f"[Session] Switched to: {latest.name} (watermark={_jsonl_watermark})")
        return True

    return True


# ================= tmux 通信 =================

async def send_to_codex(message: str):
    """通过 tmux send-keys 发送消息给 Codex。"""
    # Escape 退出现有 TUI 状态
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "Escape", ""
    )
    await proc.communicate()
    await asyncio.sleep(0.3)

    # 发送消息
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", message, ""
    )
    await proc.communicate()
    await asyncio.sleep(0.1)

    # 回车
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", "Enter", ""
    )
    await proc.communicate()
    logger.info(f"[Bridge -> Codex] {message[:100]}")


async def start_codex_in_tmux():
    """启动 Codex 交互模式到 tmux codex 会话。"""
    # 确保 tmux session 存在
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

        # 清空可能的残留输入
        for key in ["C-c", "C-c"]:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
            )
            await proc.communicate()
            await asyncio.sleep(0.2)

        # 启动 Codex
        # --no-alt-screen: TUI 输出不切屏，方便 send-keys 交互
        # --sandbox danger-full-access: 全权限沙箱
        # --ask-for-approval on-request: Codex 自己判断是否需要问用户
        cmd = "cd /root && codex --no-alt-screen --sandbox danger-full-access --ask-for-approval on-request"
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", cmd, "Enter"
        )
        await proc.communicate()
        logger.info(f"[Start] Codex launched in tmux session '{TMUX_SESSION}'")
        # 等待 Codex 初始化
        await asyncio.sleep(8)

    # 无论如何，启动时都要绑定最新 session JSONL
    refresh_session_jsonl()


async def stop_codex_in_tmux():
    """发送 Ctrl+C 停止 Codex。"""
    for key in ["C-c", "Enter", "C-c"]:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", key, ""
        )
        await proc.communicate()
        await asyncio.sleep(0.3)
    logger.info("[Stop] Sent Ctrl+C to Codex")


async def restart_codex_in_tmux():
    """重启 Codex（强杀 + 重新启动）。"""
    logger.info("[Restart] Restarting Codex...")
    await stop_codex_in_tmux()
    await asyncio.sleep(2)

    # 重建 session
    proc = await asyncio.create_subprocess_exec(
        "tmux", "kill-session", "-t", TMUX_SESSION, "2>/dev/null || true"
    )
    await proc.communicate()
    await asyncio.sleep(0.5)

    proc = await asyncio.create_subprocess_exec(
        "tmux", "new-session", "-d", "-s", TMUX_SESSION,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    await asyncio.sleep(1)

    # 启动 Codex
    cmd = "cd /root && codex --no-alt-screen --sandbox danger-full-access --ask-for-approval on-request"
    proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", f"{TMUX_SESSION}:", cmd, "Enter"
    )
    await proc.communicate()

    # 等待 Codex 初始化，然后绑定最新 session JSONL
    await asyncio.sleep(8)
    refresh_session_jsonl()
    logger.info("[Restart] Codex restarted")


# ================= QQ API =================

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
    _access_token = data.get("access_token", "")
    if not _access_token:
        raise RuntimeError(f"Failed to get token: {data}")
    expires_in = int(data.get("expires_in", 7200))
    _token_expires_at = time.time() + expires_in
    logger.info(f"[Token] Refreshed, expires in {expires_in}s")
    return _access_token


async def get_gateway_url() -> str:
    token = await ensure_token()
    client = get_http_client()
    resp = await client.get(
        f"{API_BASE}{GATEWAY_URL_PATH}",
        headers={"Authorization": f"QQBot {token}", "User-Agent": "Codex-QQ-Bridge/1.0"},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    url = data.get("url")
    if not url:
        raise RuntimeError(f"Failed to get gateway URL: {data}")
    return url


async def send_input_notify(user_openid: str, msg_id: str) -> bool:
    """发送“正在输入”通知"""
    token = await ensure_token()
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "User-Agent": "Codex-QQ-Bridge/1.0",
    }
    msg_seq = _next_msg_seq()
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


async def send_message_rest(user_openid: str, content: str) -> bool:
    """发送 C2C 消息给 QQ 用户。"""
    token = await ensure_token()
    client = get_http_client()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "User-Agent": "Codex-QQ-Bridge/1.0",
    }
    msg_seq = _next_msg_seq()
    display = content[:1500] + "\n\n... (truncated)" if len(content) > 1500 else content
    body = {"markdown": {"content": display}, "msg_type": 2, "msg_seq": msg_seq}

    try:
        resp = await client.post(
            f"{API_BASE}/v2/users/{user_openid}/messages",
            headers=headers, json=body, timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.error(f"[Send] Failed [{resp.status_code}]: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.error(f"[Send] Exception: {e}")
        return False


# ================= QQ WS 通信 =================

async def send_identify(ws):
    token = await ensure_token()
    payload = {
        "op": 2,
        "d": {
            "token": f"QQBot {token}",
            "intents": (1 << 25) | (1 << 30) | (1 << 12) | (1 << 26),
            "shard": [0, 1],
            "properties": {"$os": "Linux", "$browser": "codex-qq-bridge", "$device": "codex-qq-bridge"},
        },
    }
    await ws.send_json(payload)
    logger.info("[WS] Identify sent")


async def _heartbeat_sender(ws, interval: float):
    try:
        while _running and ws and not ws.closed:
            await asyncio.sleep(interval)
            if ws and not ws.closed:
                await ws.send_json({"op": 1, "d": _last_seq})
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.debug(f"[Heartbeat] Error: {e}")


# ================= MASTER_OPENID 自动绑定 =================

def _save_master_openid(openid: str):
    """持久化 MASTER_OPENID 到 .env。"""
    global MASTER_OPENID
    if openid == MASTER_OPENID:
        return
    candidates = [
        Path(".env"),
        Path(__file__).parent / ".env",
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
                logger.info(f"[AutoBind] MASTER_OPENID -> {openid}")
                return
            except Exception as e:
                logger.error(f"[AutoBind] Save failed: {e}")


# ================= 消息处理 =================

async def handle_c2c_message(d: dict):
    """处理 QQ C2C 消息。"""
    global _last_msg_id, _bot_openid, _is_generating, _generating_since

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
    if is_duplicate_inbound(user_openid, content or build_attachment_text(attachments)):
        logger.info(f"[Recv] duplicate inbound skipped: openid={user_openid} content={content[:50]}")
        return

    _last_msg_id = msg_id
    _is_generating = True
    _generating_since = time.time()
    logger.info(f"[Recv] openid={user_openid}: content={content[:50]}, attachments={len(attachments)}")

    # Auto-bind MASTER_OPENID
    if not MASTER_OPENID or user_openid != MASTER_OPENID:
        _save_master_openid(user_openid)

    # 命令处理
    cmd = content.strip().lower()

    if cmd in ["/new", "/reset", "/qingkong", "/xin duihua"]:
        _is_generating = False
        logger.info("[Recv] New session command")
        await restart_codex_in_tmux()
        await send_message_rest(user_openid, "✅ Codex 已重启，新会话已开始。")
        return

    if cmd in ["/stop", "/tingzhi", "/kill"]:
        _is_generating = False
        logger.info("[Recv] Stop command")
        await stop_codex_in_tmux()
        await send_message_rest(user_openid, "⛔ Codex 已停止。")
        return

    # ── 处理附件（图片/语音/视频/文件） ─────────────
    att_text = build_attachment_text(attachments) if attachments else ""
    if content and att_text:
        msg = content + "\n\n" + att_text
    elif att_text:
        msg = "用户发来了附件:\n" + att_text
    else:
        msg = content

    # 转发给 Codex
    logger.info(f"[QQ -> Codex] {msg[:120]}")
    await send_to_codex(msg)


def build_attachment_text(attachments: list) -> str:
    """构建附件文本（图片/语音/视频/文件）。"""
    lines = []
    for att in attachments:
        att_url = str(att.get("url", "")).strip()
        att_type = str(att.get("content_type", "")).strip()
        att_name = str(att.get("filename", "file")).strip()
        if not att_url:
            continue
        if "image" in att_type:
            lines.append(f"🖼 图片: {att_url}")
        elif "audio" in att_type or "voice" in att_type:
            lines.append(f"🎵 语音: {att_url}")
        elif "video" in att_type:
            lines.append(f"🎬 视频: {att_url}")
        else:
            lines.append(f"📎 文件({att_name}): {att_url}")
    return "\n".join(lines)


# ================= JSONL 轮询 =================

async def jsonl_poll():
    """后台轮询 Codex session JSONL，增量推送回复到 QQ。"""
    global _jsonl_watermark, _last_sent_ts, _is_generating, _last_typing_sent_time, _generating_since

    # 启动时绑定最新的 session JSONL
    refresh_session_jsonl()

    while _running:
        now = time.time()

        # _is_generating 超时自动 reset（300s，防 Codex 崩溃永久卡死）
        if _is_generating and _generating_since > 0 and (now - _generating_since > 300):
            logger.warning(f"[Poll] _is_generating timeout ({int(now - _generating_since)}s), auto-reset")
            _is_generating = False
            _generating_since = 0.0

        # 触发/续杯“正在输入中”的顶部状态
        if _is_generating and _last_msg_id and (now - _last_typing_sent_time > 2.5):
            asyncio.create_task(send_input_notify(MASTER_OPENID, _last_msg_id))
            _last_typing_sent_time = now

        await asyncio.sleep(2)

        try:
            # 1. 检测 session 切换（/new 后会有新文件）
            refresh_session_jsonl()

            if not _jsonl_path or not _jsonl_path.exists():
                await asyncio.sleep(1)
                continue

            # 2. 读取文件所有行（仅读取一次，防止多次读取的竞争问题）
            with open(_jsonl_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            curr_lines = len(lines)

            # 处理日志截断（文件变小 = 被重写了）
            if curr_lines < _jsonl_watermark:
                logger.info(f"[Poll] Log truncated ({_jsonl_watermark} -> {curr_lines}), resetting watermark")
                _jsonl_watermark = 0

            if curr_lines <= _jsonl_watermark:
                continue

            pushed = 0
            for line in lines[_jsonl_watermark:curr_lines]:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)

                    # 时间戳去重（防文件截断/rotate 后历史消息重推）
                    ts = obj.get("timestamp", "")
                    if ts and _last_sent_ts and ts <= _last_sent_ts:
                        continue

                    text = translate_structured_line(obj)
                    if text and isinstance(text, str) and text.strip():
                        if is_duplicate_reply(text):
                            logger.info(f"[Poll] duplicate reply skipped: {text[:80]}")
                            if ts:
                                _last_sent_ts = ts
                            continue
                        logger.info(f"[Poll -> QQ] ts={ts} {text[:80]}")
                        _is_generating = False
                        _generating_since = 0.0
                        if ts:
                            _last_sent_ts = ts
                        await send_message_rest(MASTER_OPENID, text.strip())
                        await asyncio.sleep(0.3)
                        pushed += 1
                except Exception as e:
                    logger.warning(f"[Poll] line skipped: {e}")

            _jsonl_watermark = curr_lines
            if pushed:
                logger.info(f"[Poll] pushed {pushed} structured msgs")

        except Exception as e:
            logger.error(f"[Poll] Error: {e}")


# ================= WS 事件循环 =================

async def event_loop(ws):
    global _session_id, _last_seq, _running, _ws

    _ws = ws
    _last_seq = None
    heartbeat_task = asyncio.create_task(_heartbeat_sender(ws, HEARTBEAT_INTERVAL))

    try:
        while _running and ws and not ws.closed:
            msg = await ws.receive()
            if msg.type == 1:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
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
                    logger.info(f"[WS] Hello recv, heartbeat={heartbeat_interval:.1f}s")
                    await send_identify(ws)
                    continue

                if op == 0 and t:
                    logger.info(f"[WS] Event: {t}")
                    if t == "READY":
                        if isinstance(d, dict):
                            _session_id = d.get("session_id")
                            user = d.get("user") if isinstance(d.get("user"), dict) else {}
                            _bot_openid = str(user.get("id", ""))
                            logger.info(f"[WS] READY, session_id={_session_id}, bot_openid={_bot_openid}")
                    elif t == "C2C_MESSAGE_CREATE":
                        task = asyncio.create_task(handle_c2c_message(d))
                        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                    continue

            elif msg.type == 9:
                logger.warning("[WS] Close received")
                break

    except Exception as e:
        logger.error(f"[WS] Event loop error: {e}")
    finally:
        heartbeat_task.cancel()


# ================= Main =================

async def main():
    global _running
    _running = True

    # 启动后台 JSONL 轮询
    _poll_task = asyncio.create_task(jsonl_poll())

    # 确保 Codex tmux session 存在
    await start_codex_in_tmux()

    # 连接 QQ WS 网关
    import aiohttp

    while _running:
        try:
            gateway_url = await get_gateway_url()
            logger.info(f"[Main] Gateway URL: {gateway_url}")

            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    gateway_url,
                    timeout=aiohttp.ClientTimeout(sock_connect=CONNECT_TIMEOUT),
                ) as ws:
                    logger.info("[Main] WS connected")
                    await event_loop(ws)

        except asyncio.CancelledError:
            break
        except Exception as e:
            if _running:
                logger.error(f"[Main] Connection error: {e}")
                backoff = RECONNECT_BACKOFF[0]
                logger.info(f"[Main] Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)

    logger.info("[Main] Bridge stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        _running = False
