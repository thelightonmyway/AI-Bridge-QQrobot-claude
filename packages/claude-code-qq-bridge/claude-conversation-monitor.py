#!/usr/bin/env python3
"""
监控 Claude Code 的 JSONL 会话日志，自动提取用户消息和 AI 文本回复，写入 conversation.log。
用途：新会话启动时读取 conversation.log 快速续接任务。
输出到 shell-snapshots 目录，10KB 自动循环截断。

监听路径：/root/.claude/projects/-root/*.jsonl
这些是 Claude Code 本身的会话记录，包含未加密的用户消息和 AI 回复。
"""
import os, re, time, json, sys
from pathlib import Path

# Claude Code 真实会话日志目录（JSONL 格式）
CLAUDE_LOGS = Path("/root/.claude/projects/-root/")
OUTPUT = Path("/root/.claude/shell-snapshots/conversation.log")
MAX_SIZE = 15 * 1024  # 15KB 自动循环
CHECK_INTERVAL = 10   # 轮询间隔（秒）

# 保存偏移量的文件，重启后避免重读全部历史
OFFSET_FILE = Path("/root/.claude/shell-snapshots/monitor-offsets.json")


def log(msg: str):
    """统一日志，同时输出到 stdout 和 pm2 日志。"""
    line = f"[conversation_monitor] {msg}"
    print(line, flush=True)


def load_offsets() -> dict:
    """从磁盘加载文件偏移量。"""
    try:
        if OFFSET_FILE.exists():
            return json.loads(OFFSET_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"加载偏移量失败（将重置）: {e}")
    return {}


def save_offsets(offsets: dict):
    """安全写入偏移量（先写临时文件再 rename）。"""
    try:
        tmp = OFFSET_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(offsets, ensure_ascii=False), encoding="utf-8")
        tmp.replace(OFFSET_FILE)
    except Exception as e:
        log(f"保存偏移量失败: {e}")


def extract_text_from_content(content):
    """从 message.content 中提取纯文本。content 可能是字符串或数组。"""
    try:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(texts).strip()
    except Exception:
        pass
    return ""


def extract_dialogue_from_jsonl(jsonl_path):
    """从 Claude Code JSONL 日志中提取对话内容。"""
    entries = []
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return entries

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        try:
            msg_type = obj.get("type", "")
            msg = obj.get("message", {})

            if msg_type == "user":
                content = extract_text_from_content(msg.get("content", ""))
                if content and not content.startswith("{"):
                    entries.append(("user", content))

            elif msg_type == "assistant":
                content = msg.get("content", [])
                texts = []
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            t = item.get("text", "").strip()
                            if t:
                                texts.append(t)
                if texts:
                    entries.append(("assistant", "\n".join(texts)))
        except Exception as e:
            log(f"解析行异常（跳过）: {e}")
            continue

    return entries


def trim_file(path, max_size):
    """超过 max_size 时截断前面内容，循环覆盖。截断时对齐对话条目边界，避免砍在对话中间。"""
    try:
        if path.stat().st_size > max_size:
            text = path.read_text(encoding="utf-8", errors="replace")
            # 取最后 max_size 字节，回退到上一个完整条目开头（[20... 时间戳）
            tail = text[-max_size:]
            pos = tail.find("\n[20")
            if pos > 0:
                tail = tail[pos + 1:]  # 跳过换行，从 [20 开始
            elif tail.startswith("[20"):
                pass  # 已经对齐
            else:
                pos = tail.find("[20")
                if pos > 0:
                    tail = tail[pos:]
            path.write_text(tail, encoding="utf-8")
    except Exception as e:
        log(f"截断日志失败: {e}")


def write_entries(entries):
    """安全写入对话日志。"""
    try:
        trim_file(OUTPUT, MAX_SIZE)
        with open(OUTPUT, "a", encoding="utf-8") as f:
            for role, content in entries:
                ts = time.strftime("%Y-%m-%d %H:%M")
                if len(content) > 800:
                    content = content[:800] + "..."
                f.write(f"[{ts}] {role}: {content}\n")
    except Exception as e:
        log(f"写入对话日志失败: {e}")


def get_log_files():
    """安全获取 JSONL 文件列表（防文件被删导致崩溃）。"""
    try:
        files = []
        for f in CLAUDE_LOGS.glob("*.jsonl"):
            try:
                _ = f.stat()
                files.append(f)
            except OSError:
                continue
        return sorted(files, key=lambda f: f.stat().st_mtime)
    except Exception as e:
        log(f"扫描日志文件失败: {e}")
        return []


def main():
    log(f"启动，监控 {CLAUDE_LOGS}*.jsonl → {OUTPUT}")
    file_offsets = load_offsets()
    need_save = False

    while True:
        try:
            log_files = get_log_files()
            if not log_files:
                time.sleep(CHECK_INTERVAL)
                continue

            new_entries = []
            for lf in log_files:
                try:
                    file_size = lf.stat().st_size
                except OSError:
                    continue

                offset = file_offsets.get(lf.name, 0)
                if file_size < offset:
                    offset = 0
                if file_size == offset:
                    continue

                try:
                    with open(lf, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(offset)
                        while True:
                            curr_pos = f.tell()
                            line = f.readline()
                            if not line:
                                break
                            # 如果没有以换行符结尾，说明是并发写入中的半截行，回滚并退出
                            if not line.endswith("\n") and not line.endswith("\r"):
                                f.seek(curr_pos)
                                break
                            
                            try:
                                line = line.strip()
                                if not line:
                                    continue
                                obj = json.loads(line)
                                msg_type = obj.get("type", "")
                                msg = obj.get("message", {})

                                if msg_type == "user":
                                    content = extract_text_from_content(
                                        msg.get("content", "")
                                    )
                                    if content and not content.startswith("{"):
                                        if not (content.startswith("<environment_context>") or content.startswith("<turn_aborted>")):
                                            new_entries.append(("user", content))

                                elif msg_type == "assistant":
                                    content = msg.get("content", [])
                                    texts = []
                                    if isinstance(content, list):
                                        for item in content:
                                            if isinstance(item, dict) and item.get("type") == "text":
                                                t = item.get("text", "").strip()
                                                if t and not t.startswith("{"):
                                                    texts.append(t)
                                    if texts:
                                        new_entries.append(("assistant", "\n".join(texts)))
                            except Exception as e:
                                log(f"解析行异常（跳过）: {e}")
                            
                            file_offsets[lf.name] = f.tell()
                            need_save = True
                except OSError:
                    continue

            if new_entries:
                write_entries(new_entries)
                log(f"写入 {len(new_entries)} 条对话")

            if need_save:
                save_offsets(file_offsets)
                need_save = False

        except Exception as e:
            log(f"主循环异常（继续运行）: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("收到退出信号")
        sys.exit(0)
    except Exception as e:
        log(f"异常退出: {e}")
        sys.exit(1)
