# Configuration

## Environment Variables

Configuration is primarily managed through a `.env` file in the project root or system environment variables.

### LLM Provider

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `DEFAULT_MODEL` | Default LLM model | `openrouter/gpt-4o` |

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

### Security

| Variable | Description | Default |
|----------|-------------|---------|
| `DM_POLICY` | DM access policy | `pairing` |
| `WEB_SECRET_KEY` | Admin web secret | — |
| `WEB_CORS_ORIGINS` | Allowed CORS origins | `*` |
| `EXEC_SECURITY` | Tool execution security | `deny` |
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
| `LOG_FILE` | Log file path | `data/raven.log` |
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
