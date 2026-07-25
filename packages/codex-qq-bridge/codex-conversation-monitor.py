#!/usr/bin/env python3
# ============================================================
# 核心规则（永远不准修改）：
# 只抓两种文本 —— 【USER】用户说的话，【ASSISTANT】AI回的话。
# 不要抓思考过程、工具调用、工具结果、系统消息，那些没意义。
# 10KB 轮询截断。不改逻辑，不加字段，不扩展。
# ============================================================
import json, time
from pathlib import Path

SESSION_DIR = Path('/root/.codex/sessions/')
LOG_FILE = Path('/root/codex-memory/conversation.log')
OFFSETS_FILE = Path('/root/codex-memory/file_offsets.json')
MAX_SIZE = 15 * 1024

def load_offsets():
    try:
        return json.loads(OFFSETS_FILE.read_text()) if OFFSETS_FILE.exists() else {}
    except:
        return {}

def save_offsets(offsets):
    tmp = OFFSETS_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(offsets, f, ensure_ascii=False)
    tmp.replace(OFFSETS_FILE)

def trim_log():
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_SIZE:
        try:
            content = LOG_FILE.read_text(encoding='utf-8', errors='ignore')
            truncated = content[-MAX_SIZE:]
            if '\n' in truncated:
                truncated = truncated[truncated.index('\n') + 1:]
            LOG_FILE.write_text(truncated, encoding='utf-8')
        except:
            # 备用方案：防止文本解析崩溃，降级使用字节截断
            try:
                LOG_FILE.write_bytes(LOG_FILE.read_bytes()[-MAX_SIZE:])
            except:
                pass

def main():
    offsets = load_offsets()
    print('[monitor] started', flush=True)
    while True:
        events = []
        for jf in sorted(SESSION_DIR.rglob('*.jsonl'), key=lambda p: p.stat().st_mtime):
            key = str(jf)
            try:
                fsize = jf.stat().st_size
            except:
                continue
            offset = offsets.get(key, 0)
            if fsize < offset:
                offset = 0
            if fsize == offset:
                continue
            try:
                with open(jf, 'r', encoding='utf-8', errors='ignore') as fh:
                    fh.seek(offset)
                    while True:
                        curr_pos = fh.tell()
                        line = fh.readline()
                        if not line:
                            break
                        # 如果没有换行符结尾，说明是正在写入的半截行，回滚并退出
                        if not line.endswith('\n') and not line.endswith('\r'):
                            fh.seek(curr_pos)
                            break
                        try:
                            obj = json.loads(line.strip())
                            if obj.get('type') == 'response_item':
                                pl = obj.get('payload', {})
                                if isinstance(pl, dict) and pl.get('type') == 'message':
                                    role = pl.get('role', '')
                                    if role in ('user', 'assistant'):
                                        texts = [c.get('text','').strip() for c in pl.get('content',[])
                                                 if isinstance(c, dict) and c.get('text','')]
                                        # 过滤环境初始化和中断标记等系统噪音
                                        valid_texts = []
                                        for t in texts:
                                            if t.startswith('<environment_context>') or t.startswith('<turn_aborted>'):
                                                continue
                                            valid_texts.append(t)
                                        if valid_texts:
                                            events.append((role.upper(), ' '.join(valid_texts)[:800]))
                        except:
                            pass
                        offsets[key] = fh.tell()
            except:
                continue
        if events:
            trim_log()
            save_offsets(offsets)
            now = time.strftime('%Y-%m-%d %H:%M')
            with open(LOG_FILE, 'a', encoding='utf-8') as fh:
                for role, text in events:
                    fh.write(f'[{now}] [{role}] {text}\n')
            print(f'[monitor] wrote {len(events)} msgs', flush=True)
        time.sleep(10)

if __name__ == '__main__':
    main()
