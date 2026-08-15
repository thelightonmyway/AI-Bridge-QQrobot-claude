"""每个用例都对应一个真实修复过的 bug。

移植自 SHEN-Cheng 的 bugfix 分支，已适配本地基线。
筛除的用例：test_versions_are_consistent / test_get_version_matches_version_file
（依赖对方的统一版本体系，本地各 package 版本独立，不在本轮范围）。

命名规则：test_<症状>，注释里写清原来是怎么坏的，避免以后又改回去。
"""

import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PY = (REPO_ROOT / "packages" / "claude-code-qq-bridge" / "src"
             / "claude_code_qq_bridge" / "bridge.py")


# ───────────────────────── 作用域类 bug ─────────────────────────

def _function_locals(src: str, func_name: str) -> set:
    """把单个函数摘出来编译，取它的局部变量名集合。"""
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == func_name)
    fn.args.defaults = []
    fn.args.args = []
    fn.returns = None
    for a in fn.args.kwonlyargs:
        a.annotation = None
    mod = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {}
    exec(compile(mod, "<probe>", "exec"), ns)
    return set(ns[func_name].__code__.co_varnames)


def test_restart_does_not_shadow_claude_project():
    """/clear 和 /new 曾经 100% 抛 UnboundLocalError。

    restart_claude_in_tmux() 给 CLAUDE_PROJECT 赋值却没声明 global，
    Python 于是把它当局部变量。这两个命令是唯一不传 cwd 的调用方，
    正好走到"从没赋过值"的分支，函数最后打日志时就炸了 —— 而且新会话
    其实已经起来了，用户只看到 QQ 永远不回。
    """
    src = BRIDGE_PY.read_text(encoding="utf-8")
    assert "CLAUDE_PROJECT" not in _function_locals(src, "restart_claude_in_tmux")


def test_event_loop_does_not_shadow_bot_openid():
    """_bot_openid 在 event_loop 里赋值但没声明 global，READY 后全局值仍是空。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    assert "_bot_openid" not in _function_locals(src, "event_loop")


def test_no_module_global_shadowed_anywhere():
    """整体扫一遍：任何函数都不该在没声明 global 的情况下给模块级变量赋值。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    module_globals = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    module_globals.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            module_globals.add(node.target.id)

    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        declared = {n for s in ast.walk(fn) if isinstance(s, ast.Global) for n in s.names}
        assigned = set()
        for s in ast.walk(fn):
            if isinstance(s, ast.Assign):
                for t in s.targets:
                    if isinstance(t, ast.Name):      # 只看纯名字，排除 d[k]=v
                        assigned.add(t.id)
        for name in (assigned & module_globals) - declared:
            offenders.append(f"{fn.name}:{fn.lineno} -> {name}")
    assert not offenders, "函数给模块级变量赋值却没声明 global: " + ", ".join(offenders)


# ───────────────────────── WebSocket 帧类型 ─────────────────────────

def test_ws_frame_types_are_not_magic_numbers():
    """aiohttp 里 9 是 PING、8 才是 CLOSE。写死 9 会把网关心跳当断线。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    assert "msg.type == 9" not in src
    assert "msg.type == 1" not in src
    assert "WSMsgType.TEXT" in src
    assert "WSMsgType.CLOSE" in src


def test_all_bridges_use_wsmsgtype():
    """三个 package 都修过同一处，别只修一个。"""
    for pkg, mod in (("claude-code-qq-bridge", "claude_code_qq_bridge"),
                     ("codex-qq-bridge", "codex_qq_bridge"),
                     ("agy-qq-bridge", "agy_qq_bridge")):
        p = REPO_ROOT / "packages" / pkg / "src" / mod / "bridge.py"
        src = p.read_text(encoding="utf-8")
        assert "msg.type == 9" not in src, f"{pkg} 仍在用魔数 9 判断 CLOSE"
        assert "WSMsgType" in src, f"{pkg} 没用 WSMsgType"


def test_heartbeat_uses_gateway_interval():
    """网关下发的 heartbeat_interval 以前算完就丢，心跳仍按写死的 15s 跑。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    hello = src.split("if op == 10:", 1)[1].split("continue", 1)[0]
    assert "_heartbeat_sender(ws, heartbeat_interval)" in hello


# ───────────────────────── msg_seq ─────────────────────────

def test_msg_seq_is_monotonic_not_random():
    """同一 msg_id 下 msg_seq 必须唯一；原来的 (时间^随机)%65536 会碰撞丢消息。"""
    from claude_code_qq_bridge import bridge

    seqs = [bridge._next_msg_seq("msg-a") for _ in range(200)]
    assert len(set(seqs)) == 200, "同一 msg_id 下出现重复 msg_seq"
    assert seqs == sorted(seqs), "msg_seq 应单调递增"
    # 不同 msg_id 各自独立计数
    assert bridge._next_msg_seq("msg-b") == 1


# ───────────────────────── .env 路径一致性 ─────────────────────────

@pytest.mark.parametrize("pkg,mod", [
    ("claude-code-qq-bridge", "claude_code_qq_bridge"),
    ("codex-qq-bridge", "codex_qq_bridge"),
])
def test_cli_env_check_matches_loader(pkg, mod):
    """cli() 的 .env 候选路径必须和 load_env() 一致。

    以前 cli() 查 ~/.env，load_env() 查 ~/AI-Bridge-QQrobot-claude/...，
    结果配置明明是对的却报"未找到 .env"直接退出。"""
    src = (REPO_ROOT / "packages" / pkg / "src" / mod / "bridge.py").read_text(encoding="utf-8")
    assert "Path.home() / '.env'" not in src
    assert 'Path.home() / ".env"' not in src
    assert "str(__import__('pathlib').Path.home() / '.env')" not in src


# ───────────────────────── 授权按键安全 ─────────────────────────

def test_interaction_guards_against_dead_claude():
    """Claude 挂了之后 pane 回到 bash，这时把 1/2/3 发进去会被当命令执行。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    body = src.split("async def handle_interaction", 1)[1]
    approve = body.split('button_data.startswith("approve:")', 1)[1]
    send_pos = approve.index("send-keys")
    guard_pos = approve.index("_pane_has_claude()")
    assert guard_pos < send_pos, "发送按键前必须先检查 pane 内有存活 Claude"


def test_interaction_ignores_missing_openid():
    """openid 取不到时曾把字面量 None 写进 .env，主人绑定永久失效。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    body = src.split("async def handle_interaction", 1)[1]
    assert "if not user_openid:" in body
    guard = body.index("logger.warning(\"[Interaction] no openid")
    save = body.index("_save_master_openid(user_openid)")
    assert guard < save


def test_save_master_openid_rejects_empty():
    from claude_code_qq_bridge import bridge

    before = bridge.MASTER_OPENID
    bridge._save_master_openid("")      # 不应写文件、不应改全局
    bridge._save_master_openid(None)
    assert bridge.MASTER_OPENID == before


# ───────────────────────── JSONL usage 位置 ─────────────────────────

def test_token_estimate_reads_message_usage(tmp_path):
    """Claude Code 把 usage 写在 message 下，顶层没有。

    只查顶层会永远取不到，退化成按字符数粗估，/resume 里永远显示 "(估)"。"""
    from claude_code_qq_bridge import bridge

    jf = tmp_path / "s.jsonl"
    jf.write_text("\n".join(json.dumps(o) for o in [
        {"type": "assistant", "message": {"model": "claude-opus-5", "usage": {
            "input_tokens": 1000, "output_tokens": 2000,
            "cache_creation_input_tokens": 3000, "cache_read_input_tokens": 4000}}},
    ]), encoding="utf-8")
    out = bridge._estimate_tokens_from_jsonl(jf)
    assert "(估)" not in out, f"没读到真实 usage，退化成了估算: {out}"
    assert "10K" in out or "10000" in out


# ───────────────────────── shell 脚本 ─────────────────────────

def test_setup_sh_placeholder_check_is_negated_grep():
    """`grep -qv PLACEHOLDER` 是"存在任意一行不含占位符"，注释行就让它恒真。"""
    src = (REPO_ROOT / "setup.sh").read_text(encoding="utf-8")
    assert "grep -qv \"YOUR_QQ_BOT\"" not in src
    assert "! grep -q \"YOUR_QQ_BOT\"" in src


def test_update_sh_cli_missing_is_not_fatal():
    """系统 python 下 console script 装在 ~/.local/bin，不该因此判定更新失败。"""
    src = (REPO_ROOT / "update.sh").read_text(encoding="utf-8")
    section = src.split("CLI_PATH=", 1)[1].split("阶段 9", 1)[0]
    assert "command -v claude-code-qq-bridge" in section
