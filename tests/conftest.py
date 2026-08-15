"""pytest 公共装置（移植自 SHEN-Cheng 的 bugfix 测试，适配本地基线）。

必须在 import bridge **之前** 设好 BRIDGE_LOG_DIR —— bridge 在模块顶层就会
建日志目录并装 FileHandler，晚了就会往真实的 ~/AI-Bridge-QQrobot-claude/logs 写。
"""

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_PKG_SRC = REPO_ROOT / "packages" / "claude-code-qq-bridge" / "src"

_TMP = Path(tempfile.mkdtemp(prefix="bridge-tests-"))
os.environ.setdefault("BRIDGE_LOG_DIR", str(_TMP / "logs"))
os.environ.setdefault("MASTER_OPENID", "test-openid")

if str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))

import pytest  # noqa: E402


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """把 bridge 的状态文件指到临时目录。"""
    from claude_code_qq_bridge import bridge

    monkeypatch.setattr(bridge, "_STATE_FILE", tmp_path / "state.json")
    return tmp_path


@pytest.fixture
def sent(monkeypatch):
    """拦截发往 QQ 的消息，返回累积列表。"""
    from claude_code_qq_bridge import bridge

    box = []

    async def _fake_send(openid, content, *, keyboard=False):
        box.append(content)
        return True

    monkeypatch.setattr(bridge, "send_message_rest", _fake_send)
    return box


@pytest.fixture
def to_claude(monkeypatch):
    """拦截发往 Claude 的消息。"""
    from claude_code_qq_bridge import bridge

    box = []

    async def _fake(msg):
        box.append(msg)
        return True

    monkeypatch.setattr(bridge, "send_to_claude", _fake)
    return box
