#!/usr/bin/env python3
"""
agy-conversation-monitor.py — AGY 多源会话监听脚本

监听两个来源，合并写入 conversation.log：
  [LOCAL]    — CLI 本地对话（~/.gemini/antigravity-cli/brain/*/transcript.jsonl）
  [QQ-C2C]   — QQ 私聊对话（/root/.agents/jiaoben/agy-memory/qq-conversation.log）

输出格式：
  [HH:MM] [LOCAL] [USER]: 用户说的话
  [HH:MM] [LOCAL] [ASST]: AGY 回复（截断 500 字）
  [HH:MM] [QQ-C2C] [USER@agy]: 用户说的话
  [HH:MM] [QQ-C2C] [ASST@agy]: AGY 回复

文件路径（稳定目录，勿删）：
  脚本：/root/.agents/jiaoben/agy-conversation-monitor.py
  输出：/root/.agents/jiaoben/agy-memory/conversation.log
  偏移：/root/.agents/jiaoben/agy-memory/file_offsets.json
  QQ源：/root/.agents/jiaoben/agy-memory/qq-conversation.log（由 router.py 写入）

启动（pm2）：
  pm2 start /root/.agents/jiaoben/agy-conversation-monitor.py \\
    --name agy-monitor --interpreter python3
  pm2 save

检查：ps aux | grep agy-conversation-monitor | grep -v grep
停止：pm2 stop agy-monitor
"""

import os
import json
import time
import glob
from pathlib import Path
from datetime import datetime

# ─── 路径配置 ─────────────────────────────────────────────
BRAIN_DIR    = Path("/root/.gemini/antigravity-cli/brain")
BASE_DIR     = Path("/root/.agents/jiaoben/agy-memory")
QQ_CONV_LOG  = BASE_DIR / "qq-conversation.log"
OUTPUT       = BASE_DIR / "conversation.log"
OFFSETS      = BASE_DIR / "file_offsets.json"
MAX_SIZE     = 15 * 1024   # 15KB 自动循环截断
POLL_SEC     = 3           # 轮询间隔（秒）
# ──────────────────────────────────────────────────────────


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts}: [AGY Monitor] {msg}", flush=True)


def load_offsets() -> dict:
    if OFFSETS.exists():
        try:
            return json.loads(OFFSETS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_offsets(offsets: dict):
    OFFSETS.write_text(
        json.dumps(offsets, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def truncate_if_needed():
    """超过 MAX_SIZE 时截断前半段，保留后半段。"""
    if OUTPUT.exists() and OUTPUT.stat().st_size > MAX_SIZE:
        content = OUTPUT.read_text(encoding="utf-8", errors="ignore")
        keep = content[len(content) // 2:]
        first_nl = keep.find("\n")
        if first_nl != -1:
            keep = keep[first_nl + 1:]
        OUTPUT.write_text(f"[...日志已截断...]\n{keep}", encoding="utf-8")
        log("conversation.log 超过 10KB，已截断前半段")


def extract_text(content) -> str:
    """从 content 字段提取纯文本（字符串或数组均可）。"""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts).strip()
    return ""


def clean_user_text(text: str) -> str:
    """
    清洗 USER 消息，提取真实用户话语：
      1. CLI 直接对话：提取 <USER_REQUEST> 标签内的内容
      2. QQ 群聊：含 [Current message] 前缀时，只保留其后的部分
      3. 其余：原文兜底
    """
    import re
    match = re.search(r'<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    if '[Current message]' in text:
        text = text.split('[Current message]', 1)[1].strip()
    return text


# ──────────────────────────────────────────────────────────
# 来源一：CLI 本地对话（brain transcript）
# ──────────────────────────────────────────────────────────

def process_transcript(jsonl_path: Path, offsets: dict, session_id: str, max_entries: int = 0) -> list:
    """增量读取 transcript.jsonl，返回新的日志行列表（[LOCAL] 标签）。max_entries>0 时只取最后 N 条。"""
    key = str(jsonl_path)
    offset = offsets.get(key, 0)

    try:
        raw = jsonl_path.read_bytes()
    except Exception:
        return []

    new_data = raw[offset:]
    if not new_data:
        return []

    # 检查末尾是否是完整行，如果不是则截断到最后一个换行符，防并发写入乱码/丢失
    if not new_data.endswith(b'\n') and not new_data.endswith(b'\r'):
        last_nl = max(new_data.rfind(b'\n'), new_data.rfind(b'\r'))
        if last_nl == -1:
            return []
        new_data = new_data[:last_nl + 1]

    entries = []
    for line in new_data.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        t   = obj.get("type", "")
        src = obj.get("source", "")

        if t == "USER_INPUT":
            content = obj.get("content", "")
            text = extract_text(content) or obj.get("display", "")
            text = clean_user_text(text)
            if text:
                # 过滤环境初始化和中断等系统噪音
                if not (text.startswith("<environment_context>") or text.startswith("<turn_aborted>")):
                    ts = datetime.now().strftime("%H:%M")
                    entries.append(f"[{ts}] [LOCAL] [USER]: {text}")

        elif t == "PLANNER_RESPONSE" and src == "MODEL":
            content = obj.get("content", "")
            text = extract_text(content)
            if text:
                short = text[:800].replace("\n", " ").strip()
                if len(text) > 800:
                    short += "…"
                ts = datetime.now().strftime("%H:%M")
                entries.append(f"[{ts}] [LOCAL] [ASST]: {short}")

    # 只要数据被安全认领，更新 offset
    offsets[key] = offset + len(new_data)

    if entries and max_entries > 0:
        entries = entries[-max_entries:]

    return entries


def scan_cli(offsets: dict, initial: bool = False) -> list:
    """扫描所有 brain transcript，返回新日志行。initial=True 时每个会话只取最后 20 条。"""
    import time as _time
    cutoff = _time.time() - 86400  # 只取最近 24 小时的文件
    all_entries = []
    pattern = str(BRAIN_DIR / "*" / ".system_generated" / "logs" / "transcript.jsonl")
    for path_str in glob.glob(pattern):
        p = Path(path_str)
        if initial and p.stat().st_mtime < cutoff:
            continue
        session_id = p.parts[-4]
        entries = process_transcript(p, offsets, session_id, max_entries=20 if initial else 0)
        if entries:
            log(f"[LOCAL] 写入 {len(entries)} 条（Session: {session_id[:8]}...）")
        all_entries.extend(entries)
    return all_entries


# ──────────────────────────────────────────────────────────
# 来源二：QQ C2C 对话（由 router.py 写入）
# ──────────────────────────────────────────────────────────

def scan_qq_c2c(offsets: dict) -> list:
    """增量读取 qq-conversation.log，直接透传。"""
    if not QQ_CONV_LOG.exists():
        return []

    key = str(QQ_CONV_LOG)
    offset = offsets.get(key, 0)

    try:
        raw = QQ_CONV_LOG.read_bytes()
    except Exception:
        return []

    new_data = raw[offset:]
    if not new_data:
        return []

    # 检查末尾是否是完整行，如果不是则截断到最后一个换行符
    if not new_data.endswith(b'\n') and not new_data.endswith(b'\r'):
        last_nl = max(new_data.rfind(b'\n'), new_data.rfind(b'\r'))
        if last_nl == -1:
            return []
        new_data = new_data[:last_nl + 1]

    lines = [
        l.rstrip()
        for l in new_data.decode("utf-8", errors="ignore").splitlines()
        if l.strip()
    ]

    # 更新 offset 为已处理的完整字节长度
    offsets[key] = offset + len(new_data)

    if lines:
        log(f"[QQ-C2C] 写入 {len(lines)} 条")

    return lines


# ──────────────────────────────────────────────────────────
# 主循环
# ──────────────────────────────────────────────────────────

def main():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    log(f"启动，监听目录：{BRAIN_DIR}")
    log(f"监听 QQ C2C 日志：{QQ_CONV_LOG}")
    log(f"输出日志文件：{OUTPUT}")

    offsets = load_offsets()

    # 启动时扫描（只取最近24h，每会话最多20条，防止初次爆炸）
    cli_entries = scan_cli(offsets, initial=True)
    qq_entries  = scan_qq_c2c(offsets)
    total = len(cli_entries) + len(qq_entries)
    if total:
        with open(OUTPUT, "a", encoding="utf-8") as f:
            for entry in cli_entries + qq_entries:
                f.write(entry + "\n")
        save_offsets(offsets)
        truncate_if_needed()  # 写完之后再截断
        log(f"启动扫描完成，共写入 {total} 条（CLI:{len(cli_entries)} QQ-C2C:{len(qq_entries)}）")
    else:
        log("启动扫描完成，无新内容")

    # 持续轮询
    while True:
        time.sleep(POLL_SEC)

        cli_entries = scan_cli(offsets)
        qq_entries  = scan_qq_c2c(offsets)
        all_entries = cli_entries + qq_entries

        if all_entries:
            with open(OUTPUT, "a", encoding="utf-8") as f:
                for entry in all_entries:
                    f.write(entry + "\n")
            save_offsets(offsets)
            truncate_if_needed()  # 写完之后再截断


if __name__ == "__main__":
    main()
