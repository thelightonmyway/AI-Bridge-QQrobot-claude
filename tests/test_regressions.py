"""每个用例都对应一个真实修复过的 bug。

移植自 SHEN-Cheng 的 bugfix 分支，已适配本地基线。
版本一致性用例（test_versions_are_consistent / test_get_version_matches_version_file）
曾因"本地各 package 版本独立"被筛除；版本体系已统一为根 VERSION 单一来源后恢复。

命名规则：test_<症状>，注释里写清原来是怎么坏的，避免以后又改回去。
"""

import ast
import asyncio
import os
import json
import re
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


# ───────────────────────── Claude 项目路径命名 ─────────────────────────

@pytest.mark.parametrize("path,expected", [
    ("/mnt/e/wind_global", "-mnt-e-wind-global"),
    ("/mnt/e/Antarctic", "-mnt-e-Antarctic"),
    (
        "/home/xuyang/South wind/分区域/kmeans/new2026/test/claude",
        "-home-xuyang-South-wind-----kmeans-new2026-test-claude",
    ),
])
def test_path_to_claude_project_matches_claude_naming(path, expected):
    """Claude 项目目录名把非 ASCII 字母数字和连字符的字符逐个替换为 '-'。"""
    from claude_code_qq_bridge import bridge

    assert bridge.path_to_claude_project(path) == expected


def test_path_to_claude_project_does_not_collapse_separators():
    """连续的路径分隔符、空格和中文字符必须各保留一个替换后的 '-'。"""
    from claude_code_qq_bridge import bridge

    assert bridge.path_to_claude_project("/tmp/a b/中文/c") == "-tmp-a-b----c"


def test_cd_path_resolution_matches_ls(tmp_path, monkeypatch):
    """/cd 支持 ~、相对当前目录和规范化绝对路径。"""
    from claude_code_qq_bridge import bridge

    home = tmp_path / "home"
    current = tmp_path / "current"
    home.mkdir()
    current.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert bridge.resolve_path_from_cwd("~/xxx", str(current)) == (home / "xxx").resolve()
    assert bridge.resolve_path_from_cwd("relative_dir", str(current)) == (current / "relative_dir").resolve()
    absolute = tmp_path / "absolute_dir"
    assert bridge.resolve_path_from_cwd(str(absolute), str(current)) == absolute.resolve()


def test_restart_command_quotes_workdir_and_claude_command():
    """启动命令必须安全引用带空格和 Unicode 的目录及 Claude 参数。"""
    import shlex

    from claude_code_qq_bridge import bridge

    cases = [
        "/home/xuyang/code/South wind/test",
        "/home/xuyang/code/PVanalysis/新的definition",
    ]
    for work_dir in cases:
        claude_cmd = "claude --permission-mode auto --resume session id"
        expected = f"cd {shlex.quote(work_dir)} && script -q -c {shlex.quote(claude_cmd)} /dev/null"
        assert bridge.build_claude_launch_command(work_dir, claude_cmd) == expected

    source = BRIDGE_PY.read_text(encoding="utf-8")
    restart_body = source.split("async def restart_claude_in_tmux", 1)[1]
    assert "build_claude_launch_command(work_dir, claude_cmd)" in restart_body


def test_workspace_trust_selection_reads_arrow_marker():
    """信任提示不能假设 Yes 默认选中，必须读取 TUI 的 ❯ 标记。"""
    from claude_code_qq_bridge import bridge

    prompt = """Accessing workspace: /tmp/demo
❯ No, exit
  Yes, I trust this folder

Enter to confirm"""
    assert bridge._workspace_trust_selection(prompt) == "no"
    assert bridge._workspace_trust_selection(prompt.replace("❯ No, exit", "  No, exit").replace("  Yes,", "❯ Yes,")) == "yes"
    assert bridge._workspace_trust_selection("Accessing workspace:\nYes, I trust this folder") is None


def test_workspace_trust_no_selection_moves_down_then_confirms(monkeypatch):
    """No 选中时必须先 Down，并确认 Yes 真的被选中后才 Enter。"""
    from claude_code_qq_bridge import bridge

    prompt_no = "Accessing workspace:\n❯ No, exit\n  Yes, I trust this folder\nEnter to confirm"
    prompt_yes = prompt_no.replace("❯ No, exit", "  No, exit").replace("  Yes,", "❯ Yes,")
    frames = iter([prompt_no, prompt_yes])
    sent = []

    async def capture():
        return next(frames)

    async def send(keys):
        sent.append(keys)

    monkeypatch.setattr(bridge, "_capture_pane", capture)
    monkeypatch.setattr(bridge, "_send_tmux_keys", send)
    assert asyncio.run(bridge._accept_trust_prompt_if_present(checks=1, interval=0)) is True
    assert sent == [["Down"], ["Enter"]]


def test_restart_defers_project_state_until_binding():
    """/cd 或 /resume 启动失败时，旧 cwd/project 必须保持可用。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    body = src.split("async def restart_claude_in_tmux", 1)[1]
    launch_section = body.split("# 1. 启动新 Claude", 1)[0]
    assert "_current_cwd = work_dir" not in launch_section
    assert "_current_project = path_to_claude_project(work_dir)" not in launch_section
    assert "CLAUDE_PROJECT = _current_project" not in launch_section
    assert "state update deferred until bind" in launch_section


def test_resume_failure_keeps_mapping_for_retry():
    """恢复失败后不能清空 mapping，否则用户无法立即重试同一个编号。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    resume_body = src.split('if lower.startswith(("/resume", "/huifu", "/history"))', 1)[1]
    failure = resume_body.split("if not ok:", 1)[1].split("# 绑定成功", 1)[0]
    assert "_resume_mapping.clear()" not in failure
    assert "Keep _resume_mapping intact" in failure


def test_restart_failure_logs_process_and_binding_diagnostics():
    """启动失败日志要区分进程未出现与进程出现但未绑定。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    body = src.split("async def restart_claude_in_tmux", 1)[1]
    assert "process_seen=" in body
    assert "binding_succeeded=" in body
    assert "trust_prompt_detected=" in body
    assert "pane_pids=" in body
    assert "pane_tail=" in body
    assert "claude process appeared but binding failed" in body
    assert "claude process did not appear in the pane" in body


def test_recent_session_without_jsonl_cwd_does_not_guess_from_slug(tmp_path, monkeypatch):
    """JSONL 没有 cwd 时，救援列表保持未知而非反推路径。"""
    from claude_code_qq_bridge import bridge

    projects = tmp_path / "projects" / "-mnt-e-wind-global"
    projects.mkdir(parents=True)
    (projects / "session.jsonl").write_text(
        json.dumps({"type": "user", "message": {"content": "old session"}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(tmp_path))

    sessions = bridge.discover_all_sessions()
    assert len(sessions) == 1
    assert sessions[0]["cwd"] is None
    assert "project_name_to_cwd" not in BRIDGE_PY.read_text(encoding="utf-8")


def test_recent_session_uses_jsonl_cwd_as_authority(tmp_path, monkeypatch):
    """正常会话恢复数据直接使用 JSONL 记录的 cwd。"""
    from claude_code_qq_bridge import bridge

    projects = tmp_path / "projects" / "-mnt-e-wind-global"
    projects.mkdir(parents=True)
    session_cwd = tmp_path / "real cwd with spaces"
    session_cwd.mkdir()
    (projects / "session.jsonl").write_text(
        json.dumps({"cwd": str(session_cwd), "type": "user", "message": {"content": "old session"}})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(tmp_path))
    monkeypatch.setattr(bridge, "_current_cwd", str(session_cwd))

    sessions = bridge.list_recent_sessions()
    assert sessions[0]["cwd"] == str(session_cwd)


def _write_session_jsonl(path: Path, cwd: str, title: str = "session") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join([
            json.dumps({"cwd": cwd, "type": "user", "message": {"content": title}}),
            json.dumps({"type": "assistant", "message": {"content": "reply"}}),
        ]) + "\n",
        encoding="utf-8",
    )


def test_discovery_finds_session_in_wrong_project_dir_by_jsonl_cwd(tmp_path, monkeypatch, caplog):
    """旧 project slug 不应让 cwd 正确的历史会话从默认列表消失。"""
    from claude_code_qq_bridge import bridge

    cwd = tmp_path / "home-xuyang"
    cwd.mkdir()
    jf = tmp_path / "projects" / "-wrong-project" / "AAA.jsonl"
    _write_session_jsonl(jf, str(cwd), "orphaned session")
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(tmp_path))
    monkeypatch.setattr(bridge, "_current_cwd", str(cwd))
    monkeypatch.setattr(bridge, "_current_project", bridge.path_to_claude_project(str(cwd)))

    with caplog.at_level("WARNING", logger="claude_code_bridge"):
        sessions = bridge.list_recent_sessions()
    assert [session["id"] for session in sessions] == ["AAA"]
    assert sessions[0]["project"] == "-wrong-project"
    assert "[session-discovery] project mismatch" in caplog.text


def test_default_discovery_excludes_other_cwds(tmp_path, monkeypatch):
    """默认 /resume 只聚合当前 cwd，不混入其它项目的历史。"""
    from claude_code_qq_bridge import bridge

    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    _write_session_jsonl(tmp_path / "projects" / "foo" / "AAA.jsonl", str(cwd_a))
    _write_session_jsonl(tmp_path / "projects" / "bar" / "BBB.jsonl", str(cwd_b))
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(tmp_path))
    monkeypatch.setattr(bridge, "_current_cwd", str(cwd_a))

    sessions = bridge.list_recent_sessions()
    assert [session["id"] for session in sessions] == ["AAA"]


def test_discovery_all_lists_top_level_sessions_and_skips_subagents(tmp_path, monkeypatch):
    """救援视图扫描所有项目目录，但不递归进入 subagents。"""
    from claude_code_qq_bridge import bridge

    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    _write_session_jsonl(tmp_path / "projects" / "foo" / "AAA.jsonl", str(cwd_a))
    _write_session_jsonl(tmp_path / "projects" / "bar" / "BBB.jsonl", str(cwd_b))
    _write_session_jsonl(
        tmp_path / "projects" / "foo" / "AAA" / "subagents" / "agent.jsonl",
        str(cwd_b),
    )
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(tmp_path))

    sessions = bridge.discover_all_sessions()
    assert {session["id"] for session in sessions} == {"AAA", "BBB"}
    assert all("subagents" not in session["jsonl_path"] for session in sessions)


def test_discovery_deduplicates_session_ids_preferring_newer_readable_file(tmp_path, monkeypatch):
    """同一 SID 的重复顶层文件只保留 cwd 可读且 mtime 更新的一条。"""
    from claude_code_qq_bridge import bridge

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    old = tmp_path / "projects" / "old-project" / "DUP.jsonl"
    new = tmp_path / "projects" / "new-project" / "DUP.jsonl"
    _write_session_jsonl(old, str(cwd), "old")
    _write_session_jsonl(new, str(cwd), "new")
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(tmp_path))

    sessions = bridge.discover_all_sessions()
    assert len(sessions) == 1
    assert sessions[0]["jsonl_path"] == str(new)


def test_resume_all_command_populates_rescue_mapping(tmp_path, monkeypatch):
    """/resume all 输出 cwd/project/sid，并为后续 /resume N 建立 mapping。"""
    from claude_code_qq_bridge import bridge

    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    _write_session_jsonl(tmp_path / "projects" / "foo" / "AAA.jsonl", str(cwd_a))
    _write_session_jsonl(tmp_path / "projects" / "bar" / "BBB.jsonl", str(cwd_b))
    replies = []
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(tmp_path))
    monkeypatch.setattr(bridge, "MASTER_OPENID", "user")
    monkeypatch.setattr(bridge, "is_duplicate", lambda _: False)
    async def collect_reply(_user, message):
        replies.append(message)
    monkeypatch.setattr(bridge, "send_message_rest", collect_reply)
    bridge._resume_mapping.clear()

    asyncio.run(bridge.handle_c2c_message({
        "id": "resume-all-test",
        "content": "/resume all",
        "author": {"user_openid": "user"},
    }))

    assert len(bridge._resume_mapping) == 2
    assert "cwd:" in replies[-1]
    assert "project:" in replies[-1]
    assert "sid: AAA" in replies[-1] or "sid: BBB" in replies[-1]


def test_resume_binding_requires_exact_sid_cwd_and_jsonl(tmp_path, monkeypatch):
    """恢复成功必须同时匹配请求 SID、session metadata cwd 和目标 JSONL cwd。"""
    from claude_code_qq_bridge import bridge

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    jf = tmp_path / "projects" / "wrong-project" / "AAA.jsonl"
    _write_session_jsonl(jf, str(cwd))
    monkeypatch.setattr(bridge, "_claude_session_id", "AAA")
    monkeypatch.setattr(bridge, "_pid", 123)
    monkeypatch.setattr(bridge, "_log_path", str(jf))
    monkeypatch.setattr(bridge, "_is_alive", lambda _pid: True)
    monkeypatch.setattr(bridge, "_session_data_for_pid", lambda _pid: {"cwd": str(cwd)})

    assert bridge._resume_binding_matches("AAA", str(cwd), str(jf))
    assert not bridge._resume_binding_matches("BBB", str(cwd), str(jf))
    assert not bridge._resume_binding_matches("AAA", str(tmp_path / "other"), str(jf))
    assert not bridge._resume_binding_matches("AAA", str(cwd), str(tmp_path / "other.jsonl"))


def test_resume_failure_keeps_mapping_after_real_handler_path(tmp_path, monkeypatch):
    """通过 /resume N 失败路径后，第二次仍能使用原编号。"""
    from claude_code_qq_bridge import bridge

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    jf = tmp_path / "projects" / "foo" / "AAA.jsonl"
    _write_session_jsonl(jf, str(cwd))
    bridge._resume_mapping.clear()
    bridge._resume_mapping[3] = {
        "id": "AAA", "session_id": "AAA", "jsonl_path": str(jf),
        "cwd": str(cwd), "project": "foo",
    }
    replies = []
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(tmp_path))
    monkeypatch.setattr(bridge, "MASTER_OPENID", "user")
    monkeypatch.setattr(bridge, "is_duplicate", lambda _: False)
    async def collect_reply(_user, message):
        replies.append(message)
    monkeypatch.setattr(bridge, "send_message_rest", collect_reply)
    restart_calls = []
    async def fail_restart(**kwargs):
        restart_calls.append(kwargs)
        return False, "test failure"
    monkeypatch.setattr(bridge, "restart_claude_in_tmux", fail_restart)

    asyncio.run(bridge.handle_c2c_message({
        "id": "resume-failure-test",
        "content": "/resume 3",
        "author": {"user_openid": "user"},
    }))

    assert 3 in bridge._resume_mapping
    assert "恢复会话 3 失败" in replies[-1]
    assert restart_calls == [{
        "cwd": str(cwd),
        "resume_session_id": "AAA",
        "resume_jsonl_path": str(jf),
    }]


def test_find_current_session_filters_mismatched_cwd(monkeypatch):
    """fresh /cd 只绑定 pane 内 session metadata cwd 匹配的进程。"""
    from claude_code_qq_bridge import bridge

    monkeypatch.setattr(bridge, "_tmux_pane_pids", lambda: {101, 202})
    monkeypatch.setattr(bridge, "_is_alive", lambda _pid: True)
    monkeypatch.setattr(bridge, "_is_claude_process", lambda _pid: True)
    monkeypatch.setattr(bridge, "_session_data_for_pid", lambda pid: {
        101: {"kind": "interactive", "entrypoint": "cli", "sessionId": "WRONG", "cwd": "/mnt/e/other", "updatedAt": 999},
        202: {"kind": "interactive", "entrypoint": "cli", "sessionId": "RIGHT", "cwd": "/home/xuyang", "updatedAt": 1},
    }[pid])

    assert bridge.find_current_session("/home/xuyang") == ("RIGHT", 202)


def test_startup_does_not_bind_existing_claude_from_another_cwd(monkeypatch):
    """启动时不能把 pane 内其它 cwd 的 Claude 错绑到当前项目。"""
    from claude_code_qq_bridge import bridge

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    async def fake_accept(**kwargs):
        calls.append(("trust", kwargs))
        return True

    async def fake_wait(**kwargs):
        calls.append(("wait", kwargs))
        return False

    async def fake_restart(**kwargs):
        calls.append(("restart", kwargs))
        return True, "sid=FRESH"

    monkeypatch.setattr(bridge.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(bridge, "_pane_has_claude", lambda: True)
    monkeypatch.setattr(bridge, "_accept_trust_prompt_if_present", fake_accept)
    monkeypatch.setattr(bridge, "_wait_for_any_binding", fake_wait)
    monkeypatch.setattr(bridge, "find_current_session", lambda **kwargs: calls.append(("find", kwargs)) or (None, None))
    monkeypatch.setattr(bridge, "_load_state", lambda: {})
    monkeypatch.setattr(bridge, "restart_claude_in_tmux", fake_restart)
    monkeypatch.setattr(bridge, "_current_cwd", "/tmp/target-project")

    asyncio.run(bridge.start_claude_in_tmux())

    find_calls = [kwargs for name, kwargs in calls if name == "find"]
    restart_calls = [kwargs for name, kwargs in calls if name == "restart"]
    assert find_calls == [{"expected_cwd": "/tmp/target-project"}]
    assert restart_calls == [{"cwd": "/tmp/target-project"}]


def test_apply_binding_uses_cwd_project_not_jsonl_directory(monkeypatch, tmp_path):
    """新绑定 project 应由 session cwd 计算，不能被旧 JSONL 目录覆盖。"""
    from claude_code_qq_bridge import bridge

    cwd = tmp_path / "real-cwd"
    cwd.mkdir()
    jf = tmp_path / "projects" / "-mnt-e-correct-model" / "AAA.jsonl"
    _write_session_jsonl(jf, str(cwd))
    expected_project = bridge.path_to_claude_project(str(cwd))
    monkeypatch.setattr(bridge, "_session_data_for_pid", lambda _pid: {"cwd": str(cwd)})
    monkeypatch.setattr(bridge, "_save_state", lambda: None)
    monkeypatch.setattr(bridge, "CLAUDE_PROJECT", "-old")
    monkeypatch.setattr(bridge, "_current_project", "-old")
    monkeypatch.setattr(bridge, "_current_cwd", "/old")

    bridge._apply_binding("AAA", 123, str(jf))

    assert bridge._current_cwd == str(cwd)
    assert bridge._current_project == expected_project
    assert bridge.CLAUDE_PROJECT == expected_project


def test_session_backup_copies_new_files_and_preserves_mtime(tmp_path, monkeypatch):
    """新增顶层 JSONL 会复制到稳定路径，并保留源文件 mtime。"""
    from claude_code_qq_bridge import bridge

    source_root = tmp_path / "claude"
    backup_root = tmp_path / "backup"
    source = source_root / "projects" / "-home-xuyang" / "A.jsonl"
    _write_session_jsonl(source, "/home/xuyang", "backup me")
    source_mtime = source.stat().st_mtime_ns
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(source_root))
    monkeypatch.setattr(bridge, "CLAUDE_SESSION_BACKUP_DIR", backup_root)

    stats = bridge.backup_claude_sessions()
    destination = backup_root / "projects" / "-home-xuyang" / "A.jsonl"
    assert stats == {"copied": 1, "skipped": 0, "errors": 0}
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mtime_ns == source_mtime


def test_session_backup_skips_unchanged_files(tmp_path, monkeypatch):
    """源文件 size/mtime 未变化时，重复备份不重复制。"""
    from claude_code_qq_bridge import bridge

    source_root = tmp_path / "claude"
    backup_root = tmp_path / "backup"
    source = source_root / "projects" / "foo" / "A.jsonl"
    _write_session_jsonl(source, "/home/xuyang")
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(source_root))
    monkeypatch.setattr(bridge, "CLAUDE_SESSION_BACKUP_DIR", backup_root)

    first = bridge.backup_claude_sessions()
    second = bridge.backup_claude_sessions()
    assert first["copied"] == 1
    assert second["copied"] == 0
    assert second["skipped"] >= 1


def test_session_backup_keeps_copy_after_source_deletion(tmp_path, monkeypatch):
    """源 JSONL 后续被删除时，备份副本不被删除。"""
    from claude_code_qq_bridge import bridge

    source_root = tmp_path / "claude"
    backup_root = tmp_path / "backup"
    source = source_root / "projects" / "foo" / "A.jsonl"
    _write_session_jsonl(source, "/home/xuyang")
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(source_root))
    monkeypatch.setattr(bridge, "CLAUDE_SESSION_BACKUP_DIR", backup_root)

    bridge.backup_claude_sessions()
    destination = backup_root / "projects" / "foo" / "A.jsonl"
    source.unlink()
    bridge.backup_claude_sessions()
    assert destination.exists()


def test_session_backup_skips_nested_subagent_files(tmp_path, monkeypatch):
    """备份只复制 projects/*/*.jsonl，不递归复制 subagents。"""
    from claude_code_qq_bridge import bridge

    source_root = tmp_path / "claude"
    backup_root = tmp_path / "backup"
    top_level = source_root / "projects" / "foo" / "A.jsonl"
    nested = source_root / "projects" / "foo" / "sid" / "subagents" / "agent.jsonl"
    _write_session_jsonl(top_level, "/home/xuyang")
    _write_session_jsonl(nested, "/home/xuyang")
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(source_root))
    monkeypatch.setattr(bridge, "CLAUDE_SESSION_BACKUP_DIR", backup_root)

    stats = bridge.backup_claude_sessions()
    assert stats["copied"] == 1
    assert not (backup_root / "projects" / "foo" / "sid" / "subagents").exists()


def test_session_backup_copies_history_and_warns_when_missing(tmp_path, monkeypatch, caplog):
    """history.jsonl 会复制；缺失时只 warning，不产生 fatal error。"""
    from claude_code_qq_bridge import bridge

    source_root = tmp_path / "claude"
    backup_root = tmp_path / "backup"
    source_root.mkdir()
    history = source_root / "history.jsonl"
    history.write_text('{"sessionId":"A"}\n', encoding="utf-8")
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(source_root))
    monkeypatch.setattr(bridge, "CLAUDE_SESSION_BACKUP_DIR", backup_root)

    copied = bridge.backup_claude_sessions()
    assert copied["copied"] == 1
    assert (backup_root / "history.jsonl").read_bytes() == history.read_bytes()
    history.unlink()
    with caplog.at_level("WARNING", logger="claude_code_bridge"):
        missing = bridge.backup_claude_sessions()
    assert missing["errors"] == 0
    assert "history file missing" in caplog.text


def test_session_backup_copy_error_is_nonfatal(tmp_path, monkeypatch):
    """单个 copy 错误只计数并返回，不阻断调用方。"""
    from claude_code_qq_bridge import bridge

    source_root = tmp_path / "claude"
    backup_root = tmp_path / "backup"
    source = source_root / "projects" / "foo" / "A.jsonl"
    _write_session_jsonl(source, "/home/xuyang")
    monkeypatch.setattr(bridge, "CLAUDE_HOME", str(source_root))
    monkeypatch.setattr(bridge, "CLAUDE_SESSION_BACKUP_DIR", backup_root)
    def fail_copy(*_args, **_kwargs):
        raise OSError("simulated copy failure")
    monkeypatch.setattr(bridge.shutil, "copy2", fail_copy)

    stats = bridge.backup_claude_sessions()
    assert stats["errors"] == 1
    assert stats["copied"] == 0


def test_session_backup_command_does_not_call_claude(monkeypatch):
    """/session-backup 直接执行本地备份，不调用 send_to_claude。"""
    from claude_code_qq_bridge import bridge

    replies = []
    called = []
    async def fake_backup(_trigger):
        return {"copied": 2, "skipped": 3, "errors": 0}
    async def fail_send(_message):
        called.append(True)
        raise AssertionError("/session-backup must not call Claude")
    async def collect_reply(_user, message):
        replies.append(message)
    monkeypatch.setattr(bridge, "MASTER_OPENID", "user")
    monkeypatch.setattr(bridge, "is_duplicate", lambda _: False)
    monkeypatch.setattr(bridge, "_run_session_backup", fake_backup)
    monkeypatch.setattr(bridge, "send_to_claude", fail_send)
    monkeypatch.setattr(bridge, "send_message_rest", collect_reply)

    asyncio.run(bridge.handle_c2c_message({
        "id": "session-backup-test",
        "content": "/session-backup",
        "author": {"user_openid": "user"},
    }))

    assert not called
    assert "Copied: 2" in replies[-1]
    assert "Backup: ~/.claude-session-backup" in replies[-1]


def test_session_backup_lifecycle_triggers_are_wired():
    """启动、/cd、/resume 和 /clear 成功路径都调用一次备份。"""
    src = BRIDGE_PY.read_text(encoding="utf-8")
    assert '_run_session_backup("startup")' in src
    assert '_run_session_backup("cd")' in src
    assert '_run_session_backup("resume")' in src
    assert '_run_session_backup("clear")' in src


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


# ───────────────────────── 版本一致性（根 VERSION 单一来源） ─────────────────────────

_ROOT_VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
_PYPROJECTS = [REPO_ROOT / "pyproject.toml"] + sorted(
    (REPO_ROOT / "packages").glob("*/pyproject.toml"))
_TOML_HEADER = re.compile(r"(?m)^\[([^\]]+)\]\s*$")
_TOML_VERSION = re.compile(r'(^version\s*=\s*)"([^"]*)"', re.M)


def _project_section_version(text: str) -> str | None:
    """取 [project] 表内的 version 字段值，找不到返回 None。"""
    headers = list(_TOML_HEADER.finditer(text))
    for i, m in enumerate(headers):
        if m.group(1) != "project":
            continue
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        found = _TOML_VERSION.search(text[m.start():end])
        return found.group(2) if found else None
    return None


def test_all_pyproject_versions_equal_root():
    """根 VERSION 是唯一人工维护版本，所有 pyproject [project].version 必须跟随。"""
    assert _ROOT_VERSION, "root VERSION 不能为空"
    for pf in _PYPROJECTS:
        got = _project_section_version(pf.read_text(encoding="utf-8"))
        assert got == _ROOT_VERSION, \
            f"{pf.relative_to(REPO_ROOT)} version {got} != root {_ROOT_VERSION}"


def test_sphinx_conf_has_no_hardcoded_version():
    """Sphinx 版本必须动态读根 VERSION；conf.py 只允许 0.0.0 作为缺失时的哨兵。"""
    conf = (REPO_ROOT / "docs" / "source" / "conf.py").read_text(encoding="utf-8")
    assert "VERSION" in conf, "conf.py 必须引用根 VERSION"
    for m in re.finditer(r'(?m)^\s*version\s*=\s*"(\d+\.\d+\.\d+)"', conf):
        assert m.group(1) == "0.0.0", f"conf.py 硬编码了版本 {m.group(1)}"


def test_repository_declared_versions_equal_root():
    """仓库内所有正式版本声明必须一致，不依赖本机已安装 package metadata。"""
    version_files = [
        REPO_ROOT / "VERSION",
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "packages" / "agy-qq-bridge" / "pyproject.toml",
        REPO_ROOT / "packages" / "claude-code-qq-bridge" / "pyproject.toml",
        REPO_ROOT / "packages" / "codex-qq-bridge" / "pyproject.toml",
    ]
    assert version_files[0].read_text(encoding="utf-8").strip() == _ROOT_VERSION
    for version_file in version_files[1:]:
        got = _project_section_version(version_file.read_text(encoding="utf-8"))
        assert got == _ROOT_VERSION, \
            f"{version_file.relative_to(REPO_ROOT)} version {got} != root {_ROOT_VERSION}"
