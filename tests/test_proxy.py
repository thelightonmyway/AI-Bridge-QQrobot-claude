"""WS 代理兼容：_detect_proxy_config 在 无代理 / 有代理 两种环境下的行为。

覆盖用户要求的两种环境测试：
- 无代理环境变量 → trust_env=True 直连，日志说"使用直连"
- 有代理环境变量（http/https，大小写都要）→ trust_env=True 走代理，日志脱敏
- SOCKS 代理 → 明确不支持、回退直连（不假装支持），日志必须明确说明
"""

import pytest

from claude_code_qq_bridge import bridge

PROXY_VARS = [
    "HTTPS_PROXY", "https_proxy",
    "HTTP_PROXY", "http_proxy",
    "ALL_PROXY", "all_proxy",
]


@pytest.fixture(autouse=True)
def clean_proxy_env(monkeypatch):
    """每个用例先清空所有代理环境变量，避免污染。"""
    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)


def test_no_proxy_env_direct_connect(clean_proxy_env):
    """无代理 → 直连。"""
    trust_env, note = bridge._detect_proxy_config()
    assert trust_env is True
    assert "直连" in note


def test_https_proxy_upper(clean_proxy_env, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    trust_env, note = bridge._detect_proxy_config()
    assert trust_env is True
    assert "http://127.0.0.1:7890" in note


def test_https_proxy_lower(clean_proxy_env, monkeypatch):
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7890")
    trust_env, note = bridge._detect_proxy_config()
    assert trust_env is True


def test_http_proxy_used_when_only_http_set(clean_proxy_env, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://192.168.1.5:8080")
    trust_env, note = bridge._detect_proxy_config()
    assert trust_env is True
    assert "192.168.1.5" in note


def test_all_proxy(clean_proxy_env, monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.com:3128")
    trust_env, note = bridge._detect_proxy_config()
    assert trust_env is True


def test_proxy_credentials_are_masked(clean_proxy_env, monkeypatch):
    """代理 URL 里的 user:password 绝不能出现在日志里。"""
    monkeypatch.setenv(
        "HTTPS_PROXY", "http://user:supersecret@proxy.example.com:3128")
    trust_env, note = bridge._detect_proxy_config()
    assert trust_env is True
    assert "supersecret" not in note
    assert "user:" not in note
    assert "proxy.example.com" in note


def test_socks_proxy_falls_back_to_direct(clean_proxy_env, monkeypatch):
    """SOCKS 不支持：明确回退直连，不假装支持。"""
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")
    trust_env, note = bridge._detect_proxy_config()
    assert trust_env is False, "SOCKS 应禁用 trust_env 回退直连"
    assert "SOCKS" in note
    assert "不支持" in note
    assert "直连" in note


def test_socks5h_scheme_also_falls_back(clean_proxy_env, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "socks5h://127.0.0.1:1080")
    trust_env, note = bridge._detect_proxy_config()
    assert trust_env is False
    assert "直连" in note
