# Codex / GPT-5.6 Sol setup

This optional installer configures **Claude Code → CLIProxyAPI → Codex OAuth →
`gpt-5.6-sol`** on a new Linux or macOS machine. It does not change the QQ bot
credentials in the project `.env`.

## Run the installer

From the repository root:

```bash
./scripts/setup-codex.sh
```

The script will:

1. reuse an existing `cli-proxy-api` executable or install the matching official
   CLIProxyAPI release under `~/.local/share/cliproxyapi/`;
2. create or update `~/.cli-proxy-api/config.yaml` with a local-only default
   listener (`127.0.0.1:8317`), a generated local API key, and an explicit
   `proxy-url`;
3. run CLIProxyAPI's Codex device OAuth flow;
4. start the local CLIProxyAPI server when no server is already reachable;
5. require the exact model ID `gpt-5.6-sol` from the local `/v1/models`
   endpoint;
6. back up and update both `~/.claude.json` and
   `~/.claude/settings.json`.

The installer never adds a `[1m]` suffix to the model name.

## Proxy detection

CLIProxyAPI is configured with a top-level `proxy-url`; it does not rely only on
`HTTP_PROXY` or `HTTPS_PROXY` being inherited by the server process.

The first available value is used in this order:

1. `HTTPS_PROXY` / `https_proxy`
2. `HTTP_PROXY` / `http_proxy`
3. `ALL_PROXY` / `all_proxy`
4. an existing non-empty `proxy-url` in CLIProxyAPI's config

If none is present, the interactive installer asks for a proxy URL. Leaving it
empty writes `proxy-url: "direct"`. The proxy value is not printed because a URL
may contain credentials.

Supported values are HTTP, HTTPS, SOCKS5 URLs, `direct`, and `none`.

## Claude Code settings

After the local model check succeeds, the installer writes these values into the
`env` object in **both** Claude configuration files:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:8317
ANTHROPIC_AUTH_TOKEN=<generated local key>
ANTHROPIC_MODEL=gpt-5.6-sol
CLAUDE_CODE_SUBAGENT_MODEL=gpt-5.6-sol
```

If CLIProxyAPI already uses another host or port, the actual local address is
written instead.

To prevent an older DeepSeek, Kimi, or other provider setup from continuing to
override the selected model, the installer removes conflicting top-level
`model` values and Claude/Anthropic model-selector environment keys such as
`ANTHROPIC_API_KEY`, `ANTHROPIC_DEFAULT_*_MODEL`, and stale
`CLAUDE_CODE_*_MODEL` entries. Unrelated Claude settings are preserved.

Start a **new** Claude Code session after setup. The installer does not restart
Claude, tmux, or the QQ bridge.

## Bridge lifecycle behavior

A successful setup creates a private opt-in marker at:

```text
~/.cli-proxy-api/ai-bridge-codex.env
```

Only when that marker exists does `start.sh` check CLIProxyAPI:

- `./start.sh start` ensures the configured sidecar is reachable before starting
  the bridge;
- `./start.sh restart` keeps an existing sidecar or starts it if needed;
- `./start.sh status` adds a non-secret CLIProxyAPI status line;
- `./start.sh stop` still stops only the QQ bridge, so other local Claude Code
  sessions can continue using CLIProxyAPI.

Users who never run `setup-codex.sh` retain the original bridge lifecycle with
no CLIProxyAPI checks.

## Known limitation

Some built-in Claude Code subagents (reproduced with Explore) may bypass the
configured default subagent model and request a Claude model, causing an
`unknown provider` error with a Codex-only backend. This does not affect the main
Claude Code session or normal Bridge use.

## Backups and permissions

Before changing existing files, the installer creates private backups:

- CLIProxyAPI config: `~/.cli-proxy-api/config.yaml.bak.<timestamp>`
- Claude settings: `~/.claude/backups/codex-<timestamp>/`

Directories containing credentials use mode `0700`; configuration, backup,
marker, log, and PID files use mode `0600`. API keys and OAuth records are never
printed by the installer and must not be committed to Git.

## Rollback

1. Stop using the Codex integration by removing the opt-in marker:

   ```bash
   rm ~/.cli-proxy-api/ai-bridge-codex.env
   ```

2. Restore the desired timestamped copies of `.claude.json` and `settings.json`
   from `~/.claude/backups/codex-<timestamp>/`.
3. If needed, restore a previous `config.yaml.bak.<timestamp>` as
   `~/.cli-proxy-api/config.yaml`.
4. Start a new Claude Code session.

Removing the marker changes only bridge lifecycle checks; it does not delete
OAuth records or credentials.

## Noninteractive and custom paths

For automation, set `CODEX_SETUP_NONINTERACTIVE=1`. With no detected proxy this
explicitly selects `direct`. The installer also accepts these environment
overrides:

- `CLIPROXY_BIN`
- `CLIPROXY_CONFIG_DIR` / `CLIPROXY_CONFIG`
- `CLIPROXY_INSTALL_DIR` / `CLIPROXY_BIN_LINK`
- `CLIPROXY_HOST` / `CLIPROXY_PORT`
- `CLIPROXY_AUTH_DIR`
- `CODEX_SETUP_FORCE_OAUTH=1`

These overrides are also what the test suite uses with a temporary `HOME`; tests
do not access the real CLIProxyAPI configuration or OAuth records.
