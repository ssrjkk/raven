---
description: "Every environment variable Raven reads, grouped by provider, channel, security, rate limits and paths, plus the config file."
---

# Configuration

_by [@ssrjkk](https://github.com/ssrjkk)_

## Environment Variables

Configuration is primarily managed through a `.env` file in the project root or system environment variables.

### LLM Provider

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `GROQ_API_KEY` | Groq API key | — |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `VLLM_BASE_URL` | vLLM / OpenAI-compatible local server URL | — |
| `DEFAULT_MODEL` | Default LLM model (empty = auto-discovered) | `openrouter/openai/gpt-4o` |
| `MODEL_FAST` | Model the `fast` tier answers with; empty falls back to the built-in per-provider tier table | — |
| `MODEL_BALANCED` | Model the `balanced` tier answers with, same fallback | — |
| `MODEL_QUALITY` | Model the `quality` tier answers with, same fallback | — |

Supported providers: `openai`, `anthropic`, `openrouter`, `ollama`, `vllm`, `azure`, `groq`, `bedrock`, `vertex`, `copilot`. Failover order is automatic: the first healthy provider wins.

### The bundled free model

`raven models enable-heretic` writes one line — `DEFAULT_MODEL` — into the env file this table
describes, and `raven doctor` reports the state as `Bundled Free Model`. Two names override what it
points at, which matters on an air-gapped box that mirrors the weights itself:

| Variable | Description |
|----------|-------------|
| `HERETIC_REF` | Ollama reference of the bundled GGUF, pulled as-is |
| `HERETIC_MODEL` | The `ollama/…` model string written into `DEFAULT_MODEL` |
| `HERETIC_PREVIOUS_DEFAULT_MODEL` | Written by the switch; `raven models disable-heretic` restores from it |

The value is read from the env file at gateway start and again by the config watcher, which reloads
`Settings` when the file's mtime changes — so switching the model on a running gateway takes effect
within 5 s without a restart. A `DEFAULT_MODEL` exported in the shell outranks every env file
(pydantic-settings applies the process environment last), and both `raven doctor` and the Admin card
say so instead of letting the switch appear not to hold.

### Channel Tokens

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `DISCORD_BOT_TOKEN` | Discord bot token |
| `SLACK_BOT_TOKEN` | Slack bot token |
| `SLACK_SIGNING_SECRET` | Slack signing secret |
| `MATRIX_HOMESERVER` | Matrix homeserver URL |
| `MATRIX_ACCESS_TOKEN` | Matrix access token |
| `WHATSAPP_TOKEN` | WhatsApp access token |
| `WHATSAPP_PHONE_ID` | WhatsApp phone number ID |
| `WHATSAPP_APP_SECRET` | Meta app secret; verifies `X-Hub-Signature-256` on inbound posts (falls back to `WEB_SECRET_KEY`) |
| `WHATSAPP_VERIFY_TOKEN` | Checked against `hub.verify_token` on the GET handshake (falls back to `WEB_SECRET_KEY`) |
| `SIGNAL_API_URL` | Signal (signal-cli REST API) URL |
| `IRC_SERVER` | IRC server |
| `IRC_PORT` | IRC port (default 6697) |
| `IRC_TLS` | Force TLS on/off; implied by the port when empty |
| `IRC_NICK` | IRC nickname |
| `IRC_PASSWORD` | Sent to NickServ as `IDENTIFY` once registration completes |
| `IRC_CHANNELS` | Comma-separated channels to join |
| `GOOGLECHAT_WEBHOOK_URL` | Google Chat webhook URL |
| `TEAMS_WEBHOOK_URL` | Microsoft Teams webhook URL |
| `FEISHU_WEBHOOK_URL` | Feishu/Lark webhook URL |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | Custom-app credentials used for outbound `tenant_access_token` |
| `FEISHU_ENCRYPT_KEY` | Verifies `X-Lark-Signature` on inbound event callbacks |
| `LINE_CHANNEL_TOKEN` | LINE channel token |
| `LINE_CHANNEL_SECRET` | Verifies inbound LINE webhook signatures |
| `GITHUB_TOKEN` | GitHub API token (channel + tools) |
| `GITHUB_WEBHOOK_SECRET` | Secret set on the GitHub webhook; verifies `X-Hub-Signature-256` |
| `GITLAB_TOKEN` | GitLab API token |
| `GITLAB_URL` | GitLab instance URL |
| `GITLAB_WEBHOOK_SECRET` | Verifies inbound GitLab webhook signatures |
| `EMAIL_SMTP_HOST` | Outbound SMTP server (needs `raven-agent[email]`) |
| `EMAIL_SMTP_PORT` | SMTP port, `465` uses implicit TLS (default 587 = STARTTLS) |
| `EMAIL_SMTP_USER` / `EMAIL_SMTP_PASS` | SMTP credentials |
| `EMAIL_IMAP_HOST` | Inbound IMAP server (default port 993) |
| `EMAIL_IMAP_PORT` | IMAP port |
| `EMAIL_IMAP_USER` / `EMAIL_IMAP_PASS` | IMAP credentials |
| `EMAIL_INBOX_FOLDER` | Mailbox to poll, default `INBOX` |
| `EMAIL_POLL_INTERVAL` | Seconds between inbox polls, default 30 |

### Security

| Variable | Description | Default |
|----------|-------------|---------|
| `DM_POLICY` | DM access policy | `pairing` |
| `CONTEXT_VISIBILITY` | Who the assembled conversation context is shown to: `all` sends it to everyone, `allowlist` replaces it with a filtered placeholder for users outside the allowlist, `allowlist_quote` does the same and tells the user to quote what they need | `allowlist` |
| `WEB_SECRET_KEY` | Admin web secret | — |
| `WEB_CORS_ORIGINS` | Allowed CORS origins, comma-separated. `*` is refused while credentials are allowed (Starlette answers a wildcard with the caller's Origin, so any site could read a logged-in user's responses), and a wildcard subdomain is refused too because it is matched literally and matches nothing | `http://localhost:5173,http://localhost:3000,http://localhost:18888` |
| `WEB_CORS_ALLOW_CREDENTIALS` | Send `Access-Control-Allow-Credentials`. Set `0` for a public API — that is the only configuration where `*` is accepted | `1` |
| `EXEC_SECURITY` | Gate for exec-class tools (shell, python, `process_*`, `browser_*`, MCP, plugin, git writes, db_query, CI/workflow triggers, `nodes_exec`, sandbox code) on the agent path, the orchestrator (webchat) path, task steps and both MCP transports; namespaced plugin names count too (`process.kill` = `process_kill`) | `deny` |
| `EXEC_ASK_MODE` | When `EXEC_SECURITY=ask`, which exec calls need a human yes/no; with no confirmer wired the tool denies | `always` |
| `SANDBOX_MODE` | Sandboxing mode | `non-main` |
| `SANDBOX_BACKEND` | Sandbox backend | `subprocess` |

### Rate Limiting

| Variable | Description | Default |
|----------|-------------|---------|
| `RATE_LIMIT_MAX` | Max requests per window, per client address | `60` |
| `RATE_LIMIT_WINDOW` | Window in seconds | `60` |
| `TRUST_FORWARDED_FOR` | Honour `X-Forwarded-For` from a peer that is not a proxy this project installed (see [security/overview.md §7](security/overview.md#7-rate-limiting)) | `0` |

### Web API

| Variable | Description | Default |
|----------|-------------|---------|
| `WEB_HOST` | Bind address. Loopback by default; anything else is reported by `raven doctor` and the security audit until a firewall or reverse proxy guards it | `127.0.0.1` |
| `WEB_PORT` | Port the web API and console bind. It is the one switch a running gateway cannot move: uvicorn already holds the socket, so writing it changes the next start and the console says so | `18888` |

### Paths

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_PATH` | Database file path | `data/raven.db` |
| `DATABASE_URL` | Optional Postgres DSN (`postgresql://` or `postgresql+asyncpg://`); when set, all stores use Postgres instead of SQLite | — |
| `LOG_FILE` | Log file path; warnings and above are mirrored to the same name with an `.err.log` suffix | `data/raven.log` |
| `LOG_LEVEL` | Console level; the file sinks always keep `DEBUG` and `WARNING` regardless | `INFO` |
| `JSON_LOG` | Write the log files as JSON lines (`raven logs` renders both shapes) | `true` |
| `WORKSPACE_PATH` | The workspace root — see [The workspace root](#the-workspace-root) | unset, so the working directory |
| `RAVEN_POLICY_DIR` | Directory holding the tool ruleset (`tools.json`) — read from the **process** environment (`export`, `docker run -e`), not from the env file, because the policy engine is deliberately free of the config stack. Unset, the engine reads `policy/` next to the source tree, or `raven/policy/` inside an installed wheel | the directory the package ships |

## Config File

Persistent configuration is stored in `~/.raven/config.json`:

```json
{
  "openrouter_api_key": "sk-or-v1-...",
  "dm_policy": "pairing",
  "pairing_code_length": 6
}
```

Nothing that runs reads this file: `raven doctor` shows it, and the gateway reads only the env files
below.

## Runtime switches

The names in this table can be moved while the gateway runs — from the console
(`POST /api/admin/config/key`) or by editing the env file:

| Switch | Env name | What writing it does while the gateway runs |
| --- | --- | --- |
| `default_model`, `model_fast`, `model_balanced`, `model_quality` | `DEFAULT_MODEL`, `MODEL_FAST`, `MODEL_BALANCED`, `MODEL_QUALITY` | the next call is routed to the new model |
| `ollama_base_url` | `OLLAMA_BASE_URL` | the next Ollama call goes to the new server |
| `dm_policy` | `DM_POLICY` | new DMs are admitted or refused by the new policy |
| `context_visibility` | `CONTEXT_VISIBILITY` | the next assembled context is filtered by the new mode |
| `rate_limit_max` | `RATE_LIMIT_MAX` | the live per-client limiter is rebuilt with the new budget |
| `log_level`, `json_log` | `LOG_LEVEL`, `JSON_LOG` | the log sinks are re-opened at the new level and shape |
| `openrouter_api_key`, `anthropic_api_key`, `openai_api_key`, `groq_api_key` | `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY` | the cached provider for that key is dropped, so the next call signs with the new one |
| `web_port` | `WEB_PORT` | stored for the next start — the running process already bound the socket, and the answer says `restart_required` |

Every write through the console endpoint goes `raven.core.config.apply_runtime_switch`, which validates
the value against the switch's own domain (an integer with its bounds, an enum with its members, a
credential with the provider's key shape), persists it with `write_env_value` into the highest-precedence
env file the gateway actually reads, updates the live `Settings` object, rebuilds whatever consumer cached
the old value, and answers with `applied`, `restart_required` and the warnings it collected — including the
case where the name is also exported in the shell, which outranks the env file at the next start.
`raven.core.config.refresh_settings_from_env` is the same table read the other way round, which is what
the config watcher uses when you edit a `.env` file by hand. One difference is worth knowing: a credential
rotated by hand reaches the live `Settings` object but not a provider the gateway already built, so that
provider keeps signing with the old key until the next restart. Rotate a key through the console, or
restart, to have it take effect immediately.

### Data and Workspace Overrides

| Variable | Effect | Read by |
| --- | --- | --- |
| `RAVEN_DATA_DIR` | directory for runtime artefacts such as `theme_prefs.json`, in place of `DB_PATH`'s parent | `raven/core/commands_api.py` |
| `RAVEN_WORKSPACE` | the workspace root, taking precedence over `WORKSPACE_PATH` | `raven/core/workspace.py:_decide` |
| `RAVEN_CONFIG` | the file the artifact layer takes `paths` from, searched before `./raven.json` | `raven/core/artifacts/paths.py` |

`RAVEN_DATA_DIR` and `RAVEN_WORKSPACE` are also passed into plugin subprocesses
(`raven/plugins/code/plugin.py`), so a plugin started by the gateway sees the root the
gateway resolved.

### The workspace root

One directory answers for every surface that touches the disk: the plugin tools
(`files`, `ocr`, `git`), the registry tools, the command, debugger and project-metrics
surfaces, the tool policy that gates exec arguments, and the coding agent's own file tools.
`raven/core/workspace.py` decides it once per call, in this order:

1. the root the process pinned with `set_workspace_root()` — what the MCP server does with
   `--workspace`, and what a benchmark or a test pins for its own context;
2. `RAVEN_WORKSPACE`;
3. `WORKSPACE_PATH` (the settings model), a relative value taken from the working directory;
4. the working directory the process was started in.

`raven doctor` prints the directory and names which of the four decided it, so a deployment
never has to guess. Nothing else is a root: an unset `WORKSPACE_PATH` is not an unconfined
process, it is the working directory.

Containment differs by surface on purpose:

- the plugin tools accept the workspace root **and** the system temp directory, because another
  layer often puts the file there first — the Telegram downloader writes inbound voice notes with
  `tempfile.mkstemp()` (`raven/channels/telegram/voice.py`) and `canvas_save` renders into
  `tempfile.mkdtemp()` (`raven/tools/canvas.py`) — and a tool that cannot read the file the
  channel just received is only half a tool;
- the coding agent's `confine` (`ravencode/runtime/workspace.py:confine`) accepts the workspace
  root only, so an agent session cannot leave scratch in `/tmp`;
- `WORKSPACE_ONLY=false` turns the policy-layer path check off, which `raven doctor` reports as a
  warning rather than a configuration style.

A path outside the roots raises `PermissionError` naming them; nothing is redirected into the
workspace instead. `git_status`, `git_log` and the rest refuse a repository path outside the root
rather than answering with the workspace's own commits.

## Feature Flags

Seven toggles decide which surfaces the gateway builds. They are read from
`raven/core/features.py`, taken from `.raven/features.yaml` (or `raven.yaml`) under a
`features:` key, and then overridden by the environment, which has the last word.
`raven init` writes the file with the defaults below and `raven doctor` prints the set that
is on. The last column names the file that asks about the flag.

| Flag | Default | Switch | With the flag off |
| --- | --- | --- | --- |
| `skills` | on | `RAVEN_FEATURE_SKILLS` | only built-in skills load - `raven/core/skills.py` |
| `planner` | on | `RAVEN_FEATURE_PLANNER` | `/api/task/*` is not registered - `raven/core/ops_api.py` |
| `delegation` | on | `RAVEN_FEATURE_DELEGATION` | delegated work always routes to `coder` - `raven/core/agents/multi.py` |
| `dreaming` | off | `RAVEN_FEATURE_DREAMING` | the dreaming engine refuses to run - `raven/core/dreaming/engine.py` |
| `browser` | off | `RAVEN_FEATURE_BROWSER` | the browser router is not mounted - `raven/cli/gateway_runner.py` |
| `voice` | off | `RAVEN_FEATURE_VOICE` | the voice router is not mounted - `raven/cli/gateway_runner.py` |
| `telemetry` | off | `RAVEN_FEATURE_TELEMETRY` | the analytics and A/B-testing routers are not mounted - `raven/cli/gateway_runner.py` |

ravencode keeps its own set in `ravencode/core/feature_flags.py`, switched with the `FF_`
prefix; after the unconsumed flags were removed one remains: `FF_REDIS_RATE_LIMITER`, read by
`ravencode/core/rate_limiter.py`.
