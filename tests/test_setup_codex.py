import ast
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import tarfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_CODEX = REPO_ROOT / "scripts" / "setup-codex.sh"
START_SH = REPO_ROOT / "start.sh"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _yaml_scalar(text: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}\s*:\s*(.*?)\s*$", text)
    assert match, f"missing {key}"
    raw = match.group(1)
    return str(ast.literal_eval(raw)) if raw[:1] in {'"', "'"} else raw


def _yaml_api_keys(text: str) -> list[str]:
    match = re.search(r"(?ms)^api-keys\s*:\s*\n(.*?)(?=^[A-Za-z0-9_-]+\s*:|\Z)", text)
    assert match, "missing api-keys"
    keys = []
    for raw in re.findall(r"(?m)^\s*-\s*(.*?)\s*$", match.group(1)):
        keys.append(str(ast.literal_eval(raw)) if raw[:1] in {'"', "'"} else raw)
    return keys


def _fake_cliproxy(path: Path) -> None:
    path.write_text(
        r'''#!/usr/bin/env python3
import ast
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def scalar(text, key, default=""):
    match = re.search(rf"(?m)^{re.escape(key)}\s*:\s*(.*?)\s*$", text)
    if not match:
        return default
    raw = match.group(1).strip()
    return str(ast.literal_eval(raw)) if raw[:1] in {'"', "'"} else raw


def api_keys(text):
    match = re.search(r"(?ms)^api-keys\s*:\s*\n(.*?)(?=^[A-Za-z0-9_-]+\s*:|\Z)", text)
    if not match:
        return []
    values = []
    for raw in re.findall(r"(?m)^\s*-\s*(.*?)\s*$", match.group(1)):
        values.append(str(ast.literal_eval(raw)) if raw[:1] in {'"', "'"} else raw)
    return values


args = sys.argv[1:]
if "--help" in args:
    print("CLIProxyAPI Version: test")
    raise SystemExit(0)

config = Path(args[args.index("-config") + 1])
text = config.read_text(encoding="utf-8")
if "-codex-device-login" in args:
    auth_dir = Path(os.path.expanduser(scalar(text, "auth-dir")))
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "codex-test.json").write_text('{"type":"codex"}\n', encoding="utf-8")
    with (Path.home() / "oauth-invocations.txt").open("a", encoding="utf-8") as handle:
        handle.write("codex-device-login\n")
    raise SystemExit(0)

host = scalar(text, "host", "127.0.0.1") or "127.0.0.1"
port = int(scalar(text, "port", "8317"))
valid_keys = set(api_keys(text))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/v1/models":
            self.send_response(404)
            self.end_headers()
            return
        auth = self.headers.get("Authorization", "")
        if auth.removeprefix("Bearer ") not in valid_keys:
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({"data": [{"id": "gpt-5.6-sol"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


ThreadingHTTPServer((host, port), Handler).serve_forever()
''',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _isolated_env(home: Path, fake_bin: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("CLIPROXY_") or key.startswith("CODEX_SETUP_"):
            env.pop(key)
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    env.update(
        {
            "HOME": str(home),
            "CLIPROXY_BIN": str(fake_bin),
            "CLIPROXY_HOST": "127.0.0.1",
            "CLIPROXY_PORT": str(port),
            "CODEX_SETUP_NONINTERACTIVE": "1",
            "HTTPS_PROXY": "http://127.0.0.1:7890",
        }
    )
    return env


def test_setup_codex_uses_temporary_home_and_is_idempotent(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    config_dir = home / ".cli-proxy-api"
    claude_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    claude_json = home / ".claude.json"
    settings_json = claude_dir / "settings.json"
    claude_json.write_text(
        json.dumps(
            {
                "model": "deepseek-chat",
                "keepRoot": True,
                "env": {
                    "ANTHROPIC_API_KEY": "old-deepseek-key",
                    "ANTHROPIC_MODEL": "deepseek-chat",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-chat",
                    "CLAUDE_CODE_SUBAGENT_MODEL": "kimi-k2",
                    "KEEP_ME": "root",
                },
            }
        ),
        encoding="utf-8",
    )
    settings_json.write_text(
        json.dumps(
            {
                "model": "kimi-k2",
                "permissions": {"allow": ["Read"]},
                "env": {
                    "ANTHROPIC_AUTH_TOKEN": "old-kimi-token",
                    "ANTHROPIC_MODEL": "kimi-k2",
                    "ANTHROPIC_SMALL_FAST_MODEL": "kimi-k2",
                    "CLAUDE_CODE_FALLBACK_MODEL": "deepseek-chat",
                    "KEEP_ME_TOO": "settings",
                },
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "config.yaml").write_text(
        'host: "127.0.0.1"\n'
        "port: 8317\n"
        'auth-dir: "~/.cli-proxy-api"\n'
        'proxy-url: ""\n'
        "debug: false\n"
        "api-keys:\n"
        '  - "existing-local-key"\n',
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin" / "cli-proxy-api"
    fake_bin.parent.mkdir()
    _fake_cliproxy(fake_bin)
    port = _free_port()
    env = _isolated_env(home, fake_bin, port)
    pid = None

    try:
        first = subprocess.run(
            [str(SETUP_CODEX)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert first.returncode == 0, first.stdout + first.stderr

        config_text = (config_dir / "config.yaml").read_text(encoding="utf-8")
        assert _yaml_scalar(config_text, "host") == "127.0.0.1"
        assert _yaml_scalar(config_text, "port") == str(port)
        assert _yaml_scalar(config_text, "proxy-url") == "http://127.0.0.1:7890"
        keys = _yaml_api_keys(config_text)
        assert keys[0] == "existing-local-key"
        assert len(keys) == 2
        local_key = keys[-1]
        assert len(local_key) >= 32
        assert local_key not in first.stdout
        assert local_key not in first.stderr
        assert "[1m]" not in config_text

        assert (config_dir / "codex-test.json").exists()
        assert (home / "oauth-invocations.txt").read_text(encoding="utf-8").splitlines() == [
            "codex-device-login"
        ]

        expected_env = {
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
            "ANTHROPIC_AUTH_TOKEN": local_key,
            "ANTHROPIC_MODEL": "gpt-5.6-sol",
            "CLAUDE_CODE_SUBAGENT_MODEL": "gpt-5.6-sol",
        }
        root_data = json.loads(claude_json.read_text(encoding="utf-8"))
        settings_data = json.loads(settings_json.read_text(encoding="utf-8"))
        for data in (root_data, settings_data):
            assert "model" not in data
            assert data["env"] | expected_env == data["env"]
            assert data["env"]["ANTHROPIC_BASE_URL"] == expected_env["ANTHROPIC_BASE_URL"]
            assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == local_key
            assert data["env"]["ANTHROPIC_MODEL"] == "gpt-5.6-sol"
            assert data["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "gpt-5.6-sol"
            assert "ANTHROPIC_API_KEY" not in data["env"]
            assert not any(key.startswith("ANTHROPIC_DEFAULT_") for key in data["env"])
            assert "ANTHROPIC_SMALL_FAST_MODEL" not in data["env"]
            assert "CLAUDE_CODE_FALLBACK_MODEL" not in data["env"]
        assert root_data["keepRoot"] is True
        assert root_data["env"]["KEEP_ME"] == "root"
        assert settings_data["permissions"] == {"allow": ["Read"]}
        assert settings_data["env"]["KEEP_ME_TOO"] == "settings"

        backup_dirs = sorted((claude_dir / "backups").glob("codex-*"))
        assert len(backup_dirs) == 1
        assert (backup_dirs[0] / ".claude.json").exists()
        assert (backup_dirs[0] / "settings.json").exists()
        config_backups = sorted(config_dir.glob("config.yaml.bak.*"))
        assert len(config_backups) == 1

        marker = (config_dir / "ai-bridge-codex.env").read_text(encoding="utf-8")
        assert str(fake_bin) in marker
        assert str(config_dir / "config.yaml") in marker
        assert str(port) in marker
        assert local_key not in marker
        pid = int((config_dir / "server.pid").read_text(encoding="utf-8"))
        os.kill(pid, 0)

        (home / "AI-Bridge-QQrobot-claude").symlink_to(REPO_ROOT, target_is_directory=True)
        status_env = env.copy()
        status_env["BRIDGE_LOG_DIR"] = str(tmp_path / "bridge-logs")
        status_result = subprocess.run(
            [str(START_SH), "status"],
            cwd=REPO_ROOT,
            env=status_env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert status_result.returncode == 0, status_result.stdout + status_result.stderr
        assert "Bridge not running" in status_result.stdout
        assert f"CLIProxyAPI running: pid {pid}" in status_result.stdout
        assert local_key not in status_result.stdout

        second = subprocess.run(
            [str(SETUP_CODEX)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert second.returncode == 0, second.stdout + second.stderr
        assert _yaml_api_keys((config_dir / "config.yaml").read_text(encoding="utf-8")) == keys
        assert len(list((claude_dir / "backups").glob("codex-*"))) == 1
        assert len(list(config_dir.glob("config.yaml.bak.*"))) == 1
        assert (home / "oauth-invocations.txt").read_text(encoding="utf-8").splitlines() == [
            "codex-device-login"
        ]
    finally:
        if pid is None and (config_dir / "server.pid").exists():
            pid = int((config_dir / "server.pid").read_text(encoding="utf-8"))
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(50):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)


def test_setup_codex_installs_from_isolated_release_fixture(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    fake_payload = payload_dir / "cli-proxy-api"
    _fake_cliproxy(fake_payload)

    archive = release_dir / "CLIProxyAPI_7.2.137_linux_amd64.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(fake_payload, arcname="cli-proxy-api")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum_file = release_dir / "checksums.txt"
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    release_json = release_dir / "release.json"
    release_json.write_text(
        json.dumps(
            {
                "assets": [
                    {"name": archive.name, "browser_download_url": archive.as_uri()},
                    {"name": checksum_file.name, "browser_download_url": checksum_file.as_uri()},
                ]
            }
        ),
        encoding="utf-8",
    )

    port = _free_port()
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("CLIPROXY_") or key.startswith("CODEX_SETUP_"):
            env.pop(key)
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    env.update(
        {
            "HOME": str(home),
            "CLIPROXY_BIN": str(tmp_path / "missing-cli-proxy-api"),
            "CLIPROXY_RELEASE_API": release_json.as_uri(),
            "CLIPROXY_INSTALL_DIR": str(home / ".local" / "share" / "cliproxyapi"),
            "CLIPROXY_BIN_LINK": str(home / ".local" / "bin" / "cli-proxy-api"),
            "CLIPROXY_HOST": "127.0.0.1",
            "CLIPROXY_PORT": str(port),
            "CODEX_SETUP_NONINTERACTIVE": "1",
        }
    )
    pid = None

    try:
        result = subprocess.run(
            [str(SETUP_CODEX)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        installed = home / ".local" / "share" / "cliproxyapi" / "cli-proxy-api"
        entry = home / ".local" / "bin" / "cli-proxy-api"
        assert installed.is_file() and os.access(installed, os.X_OK)
        assert entry.resolve() == installed
        assert "SHA-256" in result.stdout
        assert _yaml_scalar(
            (home / ".cli-proxy-api" / "config.yaml").read_text(encoding="utf-8"),
            "proxy-url",
        ) == "direct"
        pid = int((home / ".cli-proxy-api" / "server.pid").read_text(encoding="utf-8"))
        os.kill(pid, 0)
    finally:
        if pid is None and (home / ".cli-proxy-api" / "server.pid").exists():
            pid = int((home / ".cli-proxy-api" / "server.pid").read_text(encoding="utf-8"))
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_start_status_without_codex_marker_keeps_bridge_only_behavior(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "AI-Bridge-QQrobot-claude").symlink_to(REPO_ROOT, target_is_directory=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["BRIDGE_LOG_DIR"] = str(tmp_path / "logs")

    result = subprocess.run(
        [str(START_SH), "status"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Bridge not running" in result.stdout
    assert "CLIProxyAPI" not in result.stdout
    assert not (home / ".cli-proxy-api").exists()
