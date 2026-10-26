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

Supported providers: `openai`, `anthropic`, `openrouter`, `ollama`, `vllm`, `azure`, `groq`, `bedrock`, `vertex`, `copilot`. Failover order is automatic: the first healthy provider wins.

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
| `WEB_SECRET_KEY` | Admin web secret | — |
| `WEB_CORS_ORIGINS` | Allowed CORS origins | `http://localhost:5173,http://localhost:3000,http://localhost:18888` |
| `EXEC_SECURITY` | Gate for exec-class tools (shell, python, browser, MCP, plugin, git writes, db_query) on the agent path | `deny` |
| `EXEC_ASK_MODE` | When `EXEC_SECURITY=ask`, which exec calls need a human yes/no; with no confirmer wired the tool denies | `always` |
| `SANDBOX_MODE` | Sandboxing mode | `non-main` |
| `SANDBOX_BACKEND` | Sandbox backend | `subprocess` |

### Rate Limiting

| Variable | Description | Default |
|----------|-------------|---------|
| `RATE_LIMIT_MAX` | Max requests per window | `60` |
| `RATE_LIMIT_WINDOW` | Window in seconds | `60` |

### Paths

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_PATH` | Database file path | `data/raven.db` |
| `DATABASE_URL` | Optional Postgres DSN (`postgresql://` or `postgresql+asyncpg://`); when set, all stores use Postgres instead of SQLite | — |
| `LOG_FILE` | Log file path; warnings and above are mirrored to the same name with an `.err.log` suffix | `data/raven.log` |
| `LOG_LEVEL` | Console level; the file sinks always keep `DEBUG` and `WARNING` regardless | `INFO` |
| `JSON_LOG` | Write the log files as JSON lines (`raven logs` renders both shapes) | `true` |
| `WORKSPACE_PATH` | Workspace directory | `workspace/` |

## Config File

Persistent configuration is stored in `~/.raven/config.json`:

```json
{
  "openrouter_api_key": "sk-or-v1-...",
  "dm_policy": "pairing",
  "pairing_code_length": 6
}
```

Use `config_store.set(key, value)` to update at runtime.
