#!/usr/bin/env bash
# Configure Claude Code to use Codex OAuth through a local CLIProxyAPI server.
# This script is opt-in and does not read or modify the bridge project's .env.
set -euo pipefail

MODEL_ID="gpt-5.6-sol"
RELEASE_API="${CLIPROXY_RELEASE_API:-https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/latest}"
CONFIG_DIR="${CLIPROXY_CONFIG_DIR:-${HOME}/.cli-proxy-api}"
CONFIG_FILE="${CLIPROXY_CONFIG:-${CONFIG_DIR}/config.yaml}"
INSTALL_DIR="${CLIPROXY_INSTALL_DIR:-${HOME}/.local/share/cliproxyapi}"
BIN_ENTRY="${CLIPROXY_BIN_LINK:-${HOME}/.local/bin/cli-proxy-api}"
LOG_DIR="${CONFIG_DIR}/logs"
SERVER_LOG="${LOG_DIR}/server.log"
PIDFILE="${CONFIG_DIR}/server.pid"
MARKER_FILE="${CONFIG_DIR}/ai-bridge-codex.env"
CLAUDE_JSON="${HOME}/.claude.json"
CLAUDE_SETTINGS="${HOME}/.claude/settings.json"
NONINTERACTIVE="${CODEX_SETUP_NONINTERACTIVE:-0}"
FORCE_OAUTH="${CODEX_SETUP_FORCE_OAUTH:-0}"
TMP_WORK=""

info() { printf '[INFO] %s\n' "$*"; }
ok()   { printf '[OK]   %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die()  { printf '[ERR]  %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [ -n "${TMP_WORK}" ] && [ -d "${TMP_WORK}" ]; then
        rm -rf "${TMP_WORK}"
    fi
}
trap cleanup EXIT

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "缺少依赖: $1"
}

find_cliproxy_bin() {
    local candidate=""
    if [ -n "${CLIPROXY_BIN:-}" ]; then
        candidate="${CLIPROXY_BIN}"
    elif command -v cli-proxy-api >/dev/null 2>&1; then
        candidate="$(command -v cli-proxy-api)"
    elif [ -x "${BIN_ENTRY}" ]; then
        candidate="${BIN_ENTRY}"
    elif [ -x "${INSTALL_DIR}/cli-proxy-api" ]; then
        candidate="${INSTALL_DIR}/cli-proxy-api"
    fi

    if [ -n "${candidate}" ] && [ -x "${candidate}" ]; then
        printf '%s\n' "${candidate}"
        return 0
    fi
    return 1
}

install_cliproxy() {
    require_command curl
    require_command uname

    local os arch release_json selection asset_name asset_url checksum_url archive extract_dir installed
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    arch="$(uname -m | tr '[:upper:]' '[:lower:]')"
    case "${os}" in
        linux|darwin) ;;
        *) die "暂不支持的系统: ${os}" ;;
    esac
    case "${arch}" in
        x86_64|amd64) arch="amd64" ;;
        aarch64|arm64) arch="arm64" ;;
        *) die "暂不支持的架构: ${arch}" ;;
    esac

    TMP_WORK="$(mktemp -d "${TMPDIR:-/tmp}/ai-bridge-codex.XXXXXX")"
    release_json="${TMP_WORK}/release.json"
    info "下载 CLIProxyAPI 官方 release 元数据..."
    curl -fsSL --retry 3 --connect-timeout 15 "${RELEASE_API}" -o "${release_json}"

    selection="$(python3 - "${release_json}" "${os}" "${arch}" <<'PY'
import json
import sys
from pathlib import Path

release = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
os_name = sys.argv[2]
arch = sys.argv[3]
os_aliases = {"linux": ("linux",), "darwin": ("darwin", "macos", "mac")}[os_name]
arch_aliases = {"amd64": ("amd64", "x86_64"), "arm64": ("arm64", "aarch64")}[arch]
archives = []
checksums = []
for asset in release.get("assets", []):
    name = str(asset.get("name", ""))
    url = str(asset.get("browser_download_url", ""))
    lower = name.lower()
    if not name or not url:
        continue
    if "checksum" in lower or "sha256" in lower:
        checksums.append((name, url))
        continue
    if not lower.endswith((".tar.gz", ".tgz", ".zip")):
        continue
    if not any(token in lower for token in os_aliases):
        continue
    if not any(token in lower for token in arch_aliases):
        continue
    score = sum(token in lower for token in os_aliases + arch_aliases)
    if "cliproxyapi" in lower or "cli-proxy-api" in lower:
        score += 3
    archives.append((score, name, url))
if not archives:
    raise SystemExit("no matching release asset")
archives.sort(reverse=True)
_, name, url = archives[0]
checksum_url = checksums[0][1] if checksums else ""
print(name)
print(url)
print(checksum_url)
PY
)" || die "未找到适用于 ${os}/${arch} 的 CLIProxyAPI release 文件"

    asset_name="$(printf '%s\n' "${selection}" | python3 -c 'import sys; print(sys.stdin.readline().rstrip("\n"))')"
    asset_url="$(printf '%s\n' "${selection}" | python3 -c 'import sys; sys.stdin.readline(); print(sys.stdin.readline().rstrip("\n"))')"
    checksum_url="$(printf '%s\n' "${selection}" | python3 -c 'import sys; sys.stdin.readline(); sys.stdin.readline(); print(sys.stdin.readline().rstrip("\n"))')"
    [ -n "${asset_name}" ] && [ -n "${asset_url}" ] || die "CLIProxyAPI release 元数据不完整"

    archive="${TMP_WORK}/${asset_name}"
    info "下载 CLIProxyAPI ${os}/${arch}..."
    curl -fL --retry 3 --connect-timeout 15 "${asset_url}" -o "${archive}"

    if [ -n "${checksum_url}" ]; then
        local checksum_file
        checksum_file="${TMP_WORK}/checksums.txt"
        if curl -fsSL --retry 3 --connect-timeout 15 "${checksum_url}" -o "${checksum_file}"; then
            python3 - "${archive}" "${checksum_file}" "${asset_name}" <<'PY'
import hashlib
import re
import sys
from pathlib import Path

archive = Path(sys.argv[1])
checksum_file = Path(sys.argv[2])
asset_name = sys.argv[3]
expected = None
for line in checksum_file.read_text(encoding="utf-8", errors="ignore").splitlines():
    if asset_name not in line:
        continue
    match = re.search(r"\b([0-9a-fA-F]{64})\b", line)
    if match:
        expected = match.group(1).lower()
        break
if expected is None:
    raise SystemExit(0)
got = hashlib.sha256(archive.read_bytes()).hexdigest()
if got != expected:
    raise SystemExit("CLIProxyAPI SHA-256 checksum mismatch")
PY
            ok "CLIProxyAPI SHA-256 校验通过（如上游提供对应校验值）"
        else
            warn "无法下载上游 checksum，继续使用 HTTPS 下载结果"
        fi
    fi

    extract_dir="${TMP_WORK}/extract"
    mkdir -p "${extract_dir}"
    installed="$(python3 - "${archive}" "${extract_dir}" <<'PY'
import os
import shutil
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

archive = Path(sys.argv[1])
out = Path(sys.argv[2]).resolve()

def safe_target(name: str) -> Path:
    target = (out / name).resolve()
    try:
        target.relative_to(out)
    except ValueError as exc:
        raise SystemExit(f"unsafe archive path: {name}") from exc
    return target

if zipfile.is_zipfile(archive):
    with zipfile.ZipFile(archive) as zf:
        for item in zf.infolist():
            safe_target(item.filename)
        zf.extractall(out)
elif tarfile.is_tarfile(archive):
    with tarfile.open(archive) as tf:
        for item in tf.getmembers():
            safe_target(item.name)
            if item.issym() or item.islnk():
                raise SystemExit("archive contains a link; refusing extraction")
        tf.extractall(out)
else:
    target = out / "cli-proxy-api"
    shutil.copy2(archive, target)

candidates = []
for path in out.rglob("*"):
    if not path.is_file():
        continue
    normalized = path.name.lower().replace("_", "-")
    if normalized in {"cli-proxy-api", "cliproxyapi"}:
        candidates.append(path)
if not candidates:
    raise SystemExit("CLIProxyAPI executable not found in release archive")
chosen = sorted(candidates, key=lambda p: len(p.parts))[0]
chosen.chmod(chosen.stat().st_mode | stat.S_IXUSR)
print(chosen)
PY
)" || die "CLIProxyAPI release 解压失败"

    mkdir -p "${INSTALL_DIR}" "$(dirname "${BIN_ENTRY}")"
    install -m 0755 "${installed}" "${INSTALL_DIR}/cli-proxy-api"
    ln -sfn "${INSTALL_DIR}/cli-proxy-api" "${BIN_ENTRY}"
    ok "已安装 CLIProxyAPI: ${INSTALL_DIR}/cli-proxy-api"
}

yaml_scalar() {
    local key="$1"
    python3 - "${CONFIG_FILE}" "${key}" <<'PY'
import ast
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
pattern = re.compile(rf"^{re.escape(key)}\s*:\s*(.*)$")
for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
    if line[:1].isspace():
        continue
    match = pattern.match(line)
    if not match:
        continue
    raw = match.group(1).strip()
    if not raw:
        print("")
        break
    if raw[:1] in {'"', "'"}:
        try:
            print(ast.literal_eval(raw))
        except Exception:
            print(raw.strip('"\''))
    else:
        print(raw.split(" #", 1)[0].strip())
    break
PY
}

expand_home_path() {
    python3 - "$1" <<'PY'
import os
import sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
}

find_reusable_key() {
    python3 - "${CONFIG_FILE}" "${CLAUDE_JSON}" "${CLAUDE_SETTINGS}" <<'PY'
import ast
import json
import re
import sys
from pathlib import Path

config = Path(sys.argv[1])
keys = []
if config.exists():
    lines = config.read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^api-keys\s*:\s*$", line):
            start = i + 1
            break
    if start is not None:
        for line in lines[start:]:
            if line and not line[:1].isspace() and not line.lstrip().startswith("#"):
                break
            match = re.match(r"^\s*-\s*(.*?)\s*$", line)
            if not match:
                continue
            raw = match.group(1)
            try:
                value = ast.literal_eval(raw) if raw[:1] in {'"', "'"} else raw
            except Exception:
                value = raw.strip('"\'')
            if value:
                keys.append(str(value))
for name in sys.argv[2:]:
    path = Path(name)
    if not path.exists():
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(data, dict) or not isinstance(data.get("env"), dict):
        continue
    token = data["env"].get("ANTHROPIC_AUTH_TOKEN")
    if token and token in keys:
        print(token)
        break
PY
}

update_cli_config() {
    local timestamp
    timestamp="$(date '+%Y%m%d-%H%M%S')"
    CODEX_CONFIG_HOST="${BIND_HOST}" \
    CODEX_CONFIG_PORT="${PORT}" \
    CODEX_CONFIG_AUTH_DIR="${AUTH_DIR}" \
    CODEX_CONFIG_PROXY_URL="${PROXY_URL}" \
    CODEX_LOCAL_API_KEY="${LOCAL_API_KEY}" \
    CODEX_CONFIG_TIMESTAMP="${timestamp}" \
    python3 - "${CONFIG_FILE}" <<'PY'
import ast
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

path = Path(os.sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
old = path.read_text(encoding="utf-8") if path.exists() else ""
lines = old.splitlines()


def scalar_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw[:1] in {'"', "'"}:
        try:
            return str(ast.literal_eval(raw))
        except Exception:
            return raw.strip('"\'')
    return raw.split(" #", 1)[0].strip()


def top_level_span(key: str):
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for index, line in enumerate(lines):
        if line[:1].isspace() or not pattern.match(line):
            continue
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if candidate and not candidate[:1].isspace() and not candidate.lstrip().startswith("#"):
                break
            end += 1
        return index, end
    return None


def set_scalar(key: str, value, quoted: bool = True):
    rendered = json.dumps(str(value), ensure_ascii=False) if quoted else str(value)
    replacement = f"{key}: {rendered}"
    span = top_level_span(key)
    if span:
        lines[span[0]] = replacement
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(replacement)


api_keys = []
span = top_level_span("api-keys")
if span:
    for line in lines[span[0] + 1:span[1]]:
        match = re.match(r"^\s*-\s*(.*?)\s*$", line)
        if not match:
            continue
        value = scalar_value(match.group(1))
        if value and value not in api_keys:
            api_keys.append(value)
managed_key = os.environ["CODEX_LOCAL_API_KEY"]
if managed_key not in api_keys:
    api_keys.append(managed_key)

set_scalar("host", os.environ["CODEX_CONFIG_HOST"])
set_scalar("port", os.environ["CODEX_CONFIG_PORT"], quoted=False)
set_scalar("auth-dir", os.environ["CODEX_CONFIG_AUTH_DIR"])
set_scalar("proxy-url", os.environ["CODEX_CONFIG_PROXY_URL"])
span = top_level_span("api-keys")
block = ["api-keys:"] + [f"  - {json.dumps(key, ensure_ascii=False)}" for key in api_keys]
if span:
    lines[span[0]:span[1]] = block
else:
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(block)

new = "\n".join(lines).rstrip() + "\n"
if new == old:
    os.chmod(path, 0o600)
    print("unchanged")
    raise SystemExit(0)

if path.exists():
    backup = path.with_name(path.name + ".bak." + os.environ["CODEX_CONFIG_TIMESTAMP"])
    suffix = 1
    while backup.exists():
        backup = path.with_name(path.name + ".bak." + os.environ["CODEX_CONFIG_TIMESTAMP"] + f".{suffix}")
        suffix += 1
    shutil.copy2(path, backup)
    os.chmod(backup, 0o600)

with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
    tmp.write(new)
    temp_name = tmp.name
os.chmod(temp_name, 0o600)
os.replace(temp_name, path)
print("changed")
PY
}

socket_reachable() {
    python3 - "${CLIENT_HOST}" "${PORT}" <<'PY'
import socket
import sys
try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=0.5):
        pass
except OSError:
    raise SystemExit(1)
PY
}

model_available() {
    CODEX_LOCAL_API_KEY="${LOCAL_API_KEY}" python3 - "${BASE_URL}" "${MODEL_ID}" <<'PY'
import json
import os
import sys
import urllib.request

base_url = sys.argv[1].rstrip("/")
model = sys.argv[2]
request = urllib.request.Request(base_url + "/v1/models")
request.add_header("Authorization", "Bearer " + os.environ["CODEX_LOCAL_API_KEY"])
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(request, timeout=3) as response:
        payload = json.load(response)
except Exception:
    raise SystemExit(1)
models = {
    item.get("id") for item in payload.get("data", [])
    if isinstance(item, dict) and item.get("id")
} if isinstance(payload, dict) else set()
raise SystemExit(0 if model in models else 2)
PY
}

pid_is_running() {
    [ -f "${PIDFILE}" ] || return 1
    local pid
    pid="$(cat "${PIDFILE}" 2>/dev/null || true)"
    [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null
}

start_cliproxy() {
    mkdir -p "${LOG_DIR}"
    chmod 700 "${LOG_DIR}"
    touch "${SERVER_LOG}"
    chmod 600 "${SERVER_LOG}"

    if socket_reachable; then
        if model_available; then
            ok "CLIProxyAPI 已在 ${BASE_URL} 提供 ${MODEL_ID}"
            return 0
        fi
        die "${CLIENT_HOST}:${PORT} 已被进程占用，但无法用当前本地 key 验证 ${MODEL_ID}；未终止该进程"
    fi

    if pid_is_running; then
        local old_pid
        old_pid="$(cat "${PIDFILE}")"
        warn "发现不可达的受管 CLIProxyAPI pid ${old_pid}，仅停止该 pid 后重启"
        kill "${old_pid}" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
            kill -0 "${old_pid}" 2>/dev/null || break
            sleep 0.2
        done
    fi

    info "启动 CLIProxyAPI（日志: ${SERVER_LOG}）..."
    nohup "${CLIPROXY_BIN_PATH}" -config "${CONFIG_FILE}" >> "${SERVER_LOG}" 2>&1 &
    local pid=$!
    printf '%s\n' "${pid}" > "${PIDFILE}"
    chmod 600 "${PIDFILE}"

    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        if ! kill -0 "${pid}" 2>/dev/null; then
            rm -f "${PIDFILE}"
            die "CLIProxyAPI 启动后立即退出，请检查 ${SERVER_LOG}"
        fi
        if socket_reachable; then
            return 0
        fi
        sleep 0.25
    done
    kill "${pid}" 2>/dev/null || true
    rm -f "${PIDFILE}"
    die "CLIProxyAPI 未在 ${CLIENT_HOST}:${PORT} 就绪"
}

update_claude_settings() {
    local timestamp
    timestamp="$(date '+%Y%m%d-%H%M%S')"
    CODEX_BASE_URL="${BASE_URL}" \
    CODEX_LOCAL_API_KEY="${LOCAL_API_KEY}" \
    CODEX_MODEL_ID="${MODEL_ID}" \
    CODEX_BACKUP_TIMESTAMP="${timestamp}" \
    python3 - "${CLAUDE_JSON}" "${CLAUDE_SETTINGS}" "${HOME}/.claude/backups" <<'PY'
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

paths = [Path(os.sys.argv[1]), Path(os.sys.argv[2])]
backup_root = Path(os.sys.argv[3])
base_url = os.environ["CODEX_BASE_URL"]
token = os.environ["CODEX_LOCAL_API_KEY"]
model = os.environ["CODEX_MODEL_ID"]
loaded = []

for path in paths:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit(f"{path} must contain a JSON object")
    else:
        data = {}
    loaded.append((path, data, json.dumps(data, ensure_ascii=False, sort_keys=True)))

conflicting_exact = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "CLAUDE_CODE_MODEL",
    "CLAUDE_CODE_FALLBACK_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
}
changed = []
for path, data, before in loaded:
    data.pop("model", None)
    env = data.get("env")
    if env is None:
        env = {}
        data["env"] = env
    if not isinstance(env, dict):
        raise SystemExit(f"{path}: env must be a JSON object")
    for key in list(env):
        is_default_model = key.startswith("ANTHROPIC_DEFAULT_") and key.endswith("_MODEL")
        is_stale_claude_model = key.startswith("CLAUDE_CODE_") and key.endswith("_MODEL")
        if key in conflicting_exact or is_default_model or is_stale_claude_model:
            env.pop(key, None)
    env.update({
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
    })
    after = json.dumps(data, ensure_ascii=False, sort_keys=True)
    changed.append((path, data, before != after))

if not any(item[2] for item in changed):
    for path, _, _ in changed:
        if path.exists():
            os.chmod(path, 0o600)
    print("unchanged")
    raise SystemExit(0)

backup_dir = backup_root / ("codex-" + os.environ["CODEX_BACKUP_TIMESTAMP"])
suffix = 1
while backup_dir.exists():
    backup_dir = backup_root / ("codex-" + os.environ["CODEX_BACKUP_TIMESTAMP"] + f"-{suffix}")
    suffix += 1
backup_dir.mkdir(parents=True, mode=0o700)
os.chmod(backup_dir, 0o700)
for path, _, did_change in changed:
    if did_change and path.exists():
        destination = backup_dir / path.name
        shutil.copy2(path, destination)
        os.chmod(destination, 0o600)

for path, data, did_change in changed:
    if not did_change:
        continue
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temp_name = tmp.name
    os.chmod(temp_name, 0o600)
    os.replace(temp_name, path)
print(str(backup_dir))
PY
}

write_marker() {
    local temp_marker
    temp_marker="${MARKER_FILE}.tmp.$$"
    {
        printf 'AI_BRIDGE_CLIPROXY_BIN=%q\n' "${CLIPROXY_BIN_PATH}"
        printf 'AI_BRIDGE_CLIPROXY_CONFIG=%q\n' "${CONFIG_FILE}"
        printf 'AI_BRIDGE_CLIPROXY_HOST=%q\n' "${CLIENT_HOST}"
        printf 'AI_BRIDGE_CLIPROXY_PORT=%q\n' "${PORT}"
    } > "${temp_marker}"
    chmod 600 "${temp_marker}"
    mv "${temp_marker}" "${MARKER_FILE}"
}

require_command python3
mkdir -p "${CONFIG_DIR}" "${LOG_DIR}"
chmod 700 "${CONFIG_DIR}" "${LOG_DIR}"

if CLIPROXY_BIN_PATH="$(find_cliproxy_bin)"; then
    ok "检测到 CLIProxyAPI: ${CLIPROXY_BIN_PATH}"
else
    install_cliproxy
    CLIPROXY_BIN_PATH="${INSTALL_DIR}/cli-proxy-api"
fi
"${CLIPROXY_BIN_PATH}" --help >/dev/null 2>&1 || die "CLIProxyAPI 可执行文件验证失败"

EXISTING_HOST="$(yaml_scalar host)"
EXISTING_PORT="$(yaml_scalar port)"
EXISTING_PROXY="$(yaml_scalar proxy-url)"
EXISTING_AUTH_DIR="$(yaml_scalar auth-dir)"
BIND_HOST="${CLIPROXY_HOST:-${EXISTING_HOST:-127.0.0.1}}"
PORT="${CLIPROXY_PORT:-${EXISTING_PORT:-8317}}"
[[ "${PORT}" =~ ^[0-9]+$ ]] || die "CLIProxyAPI port 必须是整数: ${PORT}"
[ "${PORT}" -ge 1 ] && [ "${PORT}" -le 65535 ] || die "CLIProxyAPI port 超出范围: ${PORT}"
AUTH_DIR="$(expand_home_path "${CLIPROXY_AUTH_DIR:-${EXISTING_AUTH_DIR:-${CONFIG_DIR}}}")"
mkdir -p "${AUTH_DIR}"
chmod 700 "${AUTH_DIR}"

PROXY_URL=""
PROXY_SOURCE=""
for proxy_var in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy ALL_PROXY all_proxy; do
    if [ -n "${!proxy_var:-}" ]; then
        PROXY_URL="${!proxy_var}"
        PROXY_SOURCE="${proxy_var}"
        break
    fi
done
if [ -z "${PROXY_URL}" ] && [ -n "${EXISTING_PROXY}" ]; then
    PROXY_URL="${EXISTING_PROXY}"
    PROXY_SOURCE="现有 config.yaml"
fi
if [ -z "${PROXY_URL}" ]; then
    if [ "${NONINTERACTIVE}" = "1" ] || [ ! -t 0 ]; then
        PROXY_URL="direct"
        PROXY_SOURCE="显式直连"
    else
        printf '未检测到代理环境变量。请输入 CLIProxyAPI proxy-url（留空使用 direct）: '
        IFS= read -r PROXY_URL
        PROXY_URL="${PROXY_URL:-direct}"
        PROXY_SOURCE="用户输入"
    fi
fi
case "${PROXY_URL}" in
    direct|none|http://*|https://*|socks5://*|socks5h://*) ;;
    *) die "proxy-url 必须是 http/https/socks5 URL，或 direct/none" ;;
esac
info "CLIProxyAPI host/port: ${BIND_HOST}:${PORT}"
info "已显式配置 proxy-url（来源: ${PROXY_SOURCE}，值不回显）"

case "${BIND_HOST}" in
    ""|0.0.0.0|::|"[::]") CLIENT_HOST="127.0.0.1" ;;
    localhost) CLIENT_HOST="127.0.0.1" ;;
    *) CLIENT_HOST="${BIND_HOST}" ;;
esac
if [[ "${CLIENT_HOST}" == *:* ]] && [[ "${CLIENT_HOST}" != \[*\] ]]; then
    BASE_URL="http://[${CLIENT_HOST}]:${PORT}"
else
    BASE_URL="http://${CLIENT_HOST}:${PORT}"
fi

LOCAL_API_KEY="$(find_reusable_key)"
if [ -n "${LOCAL_API_KEY}" ]; then
    info "复用现有本地 CLIProxyAPI key（不回显）"
else
    LOCAL_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    info "已生成新的本地 CLIProxyAPI key（不回显）"
fi

CONFIG_RESULT="$(update_cli_config)"
if [ "${CONFIG_RESULT}" = "changed" ]; then
    ok "已备份并更新 CLIProxyAPI 配置: ${CONFIG_FILE}"
else
    ok "CLIProxyAPI 配置已是目标状态"
fi

if [ "${FORCE_OAUTH}" = "1" ] || ! find "${AUTH_DIR}" -maxdepth 1 -type f -name 'codex-*.json' -size +0c -print -quit 2>/dev/null | grep -q .; then
    info "启动 Codex device OAuth；请按 CLIProxyAPI 提示完成授权..."
    "${CLIPROXY_BIN_PATH}" -config "${CONFIG_FILE}" -codex-device-login -no-browser
    ok "Codex device OAuth 已完成"
else
    ok "检测到现有 Codex OAuth 记录，跳过重复登录（可设置 CODEX_SETUP_FORCE_OAUTH=1 强制重新登录）"
fi

start_cliproxy
if model_available; then
    ok "已确认模型可用: ${MODEL_ID}"
else
    status=$?
    if [ "${status}" -eq 2 ]; then
        die "CLIProxyAPI 可访问，但模型列表中没有 ${MODEL_ID}"
    fi
    die "无法通过本地 CLIProxyAPI 验证 ${MODEL_ID}"
fi

SETTINGS_RESULT="$(update_claude_settings)"
if [ "${SETTINGS_RESULT}" = "unchanged" ]; then
    ok "Claude Code 配置已是目标状态"
else
    ok "已备份并更新 ~/.claude.json 与 ~/.claude/settings.json"
    info "备份目录: ${SETTINGS_RESULT}"
fi

write_marker
ok "Codex / GPT-5.6 Sol 配置完成"
printf '\n'
printf '  ANTHROPIC_BASE_URL=%s\n' "${BASE_URL}"
printf '  ANTHROPIC_MODEL=%s\n' "${MODEL_ID}"
printf '  CLAUDE_CODE_SUBAGENT_MODEL=%s\n' "${MODEL_ID}"
printf '  ANTHROPIC_AUTH_TOKEN=<local key hidden>\n'
printf '\n请新开 Claude Code 会话使配置生效；本脚本不会重启 bridge、Claude 或 tmux。\n'
