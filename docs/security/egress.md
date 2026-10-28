# Network egress map

Every destination a Raven process can be reached at, named in the source that calls it. The landing
page says the assistant makes no calls to a Raven-hosted service and loads no third-party assets;
this page is what backs that sentence, and `tests/test_egress_map.py` fails if a host literal
appears in `raven/`, `ravencode/` or `aios/` without a row here, or if a row stops being used.

The scan is of host literals. A destination assembled at runtime (a region inserted into a hostname,
a deployment name supplied by the operator) appears as the prefix or the pattern the code carries.

## LLM and media providers

Reached only when that provider is selected in the model router, and with the operator's own key.

| Host | Caller | What goes out |
|------|--------|---------------|
| `api.openai.com` | `raven/core/llm/providers/openai.py`, `raven/channels/telegram/voice.py`, `raven/core/media_api.py` | chat completions, Whisper transcription of a voice note, image generation |
| `openrouter.ai` | `raven/core/llm/providers/openai.py` | completions through the OpenAI-compatible route |
| `api.anthropic.com` | `raven/core/llm/providers/anthropic.py` | completions, prompt caching |
| `api.groq.com` | `raven/core/llm/providers/groq.py` | completions |
| `api.githubcopilot.com` | `raven/core/llm/providers/copilot.py` | completions with a GitHub device token |
| `bedrock-runtime.*.amazonaws.com` | `raven/core/llm/providers/bedrock.py` | SigV4-signed inference; the `*` is the region slot the code substitutes |
| `*-aiplatform.googleapis.com` | `raven/core/llm/providers/vertex.py` | Vertex AI generate-content calls; `<region>-aiplatform.googleapis.com`, the region from the configuration |
| `your-resource.openai.azure.com` | `raven/core/llm/providers/openai.py` | pattern for `*.openai.azure.com`; the deployment host the operator configures |
| `api.replicate.com` | `raven/tools/media.py` | image and video generation jobs |

## Search tools

Used when the model calls a search tool. `html.duckduckgo.com` needs no key and no configuration, so
it is the one search engine reachable on a default install.

| Host | Caller | What goes out |
|------|--------|---------------|
| `html.duckduckgo.com` | `raven/tools/web_search.py`, `raven/plugins/browser/plugin.py`, `ravencode/runtime/tools/web.py` | the query string, POSTed to the HTML endpoint |
| `api.tavily.com` | `raven/tools/web_search.py` | the query, with `TAVILY_API_KEY` |
| `api.search.brave.com` | `raven/tools/web_search.py` | the query, with `BRAVE_API_KEY` |
| `api.bing.microsoft.com` | `raven/tools/web_search.py` | the query, with `BING_SEARCH_KEY` |
| `api.perplexity.ai` | `raven/tools/web_search.py` | the query, with `PERPLEXITY_API_KEY` |
| `www.googleapis.com` | `raven/tools/web_search.py` | `/customsearch/v1`, with `GOOGLE_SEARCH_API_KEY` and `GOOGLE_CSE_ID` |

## Channel adapters

Reached only if that channel is configured and started. A message sent to a messenger is delivered to
that messenger's API — that is the product, not a leak.

| Host | Caller | What goes out |
|------|--------|---------------|
| `api.telegram.org` | `raven/channels/telegram/*`, `raven/channels/telegram/voice.py` | Bot API sends and file downloads |
| `graph.facebook.com` | `raven/channels/whatsapp/channel.py` | WhatsApp Business Cloud messages |
| `chat.googleapis.com` | `raven/channels/googlechat/channel.py` | Google Chat hooks |
| `api.line.me` | `raven/channels/line/channel.py` | LINE push messages |
| `open.feishu.cn` | `raven/channels/feishu/channel.py` | Feishu/Lark messaging |
| `api.teams.microsoft.com` | `raven/channels/teams/channel.py` | Teams activities |

Channels driven by a vendor SDK do not name their endpoint in this repository and are therefore
outside the scan: `discord.py` reaches `discord.com` and the gateway socket, Slack's SDK reaches
`slack.com`. Matrix, IRC and Signal talk to a server the operator names — Signal's default is
`http://localhost:8080`, a local signal-cli daemon.

## Repository hosting and OAuth

| Host | Caller | What goes out |
|------|--------|---------------|
| `api.github.com` | `raven/tools/github.py`, `raven/tools/ci.py`, `raven/core/github_api.py`, `raven/channels/github/channel.py`, `raven/core/auth/oauth.py` | repo, issue, PR and workflow calls with the configured token |
| `github.com` | `raven/core/_deploy.py` (`DEPLOY_ORIGIN`), `raven/cli/doctor_cmd.py`, `raven/cli/nodes_cmd.py` | `git clone`/`fetch` of this repository; two of the three are printed text |
| `gitlab.com` | `raven/channels/gitlab/channel.py`, `raven/tools/ci.py`, `raven/core/config.py` | GitLab API calls; `gitlab_url` defaults here |
| `accounts.google.com`, `oauth2.googleapis.com` | `raven/core/auth/oauth.py` | OAuth code exchange for Google scopes |
| `login.microsoftonline.com`, `graph.microsoft.com` | `raven/core/auth/oauth.py` | OAuth code exchange for Microsoft tenants |

## Monitors

| Host | Caller | What goes out |
|------|--------|---------------|
| `api.coingecko.com` | `raven/core/monitor/checkers/price.py` | a price query per tick of that monitor |
| `status.github.com` | `raven/monitors/register_all.py` | the default target of the shipped uptime monitor; a probe per tick |

## Operator-initiated, not runtime

These happen when a person runs a command, never while the gateway is serving.

| Host | Caller | What goes out |
|------|--------|---------------|
| `ollama.com` | `raven/cli/setup_cmd.py` | downloads the Ollama installer or runs its install script |

## Fine-tuning

Training is the one feature that moves large amounts of data across the boundary in both directions, so
it is spelled out rather than left inside "LLM providers".

| Host | Caller | What goes out |
|------|--------|---------------|
| `huggingface.co` | `raven/unique/fine_tuning.py` | the base model and tokenizer you asked for (`model_type`/`model_name_or_path`), downloaded on demand when a training session loads. Gated repositories answer 401 without a `HUGGINGFACE_API_KEY`; nothing is sent up |
| `api.wandb.ai` | `raven/unique/fine_tuning.py` | **opt-in only.** Metrics, the training config, and — through `TrainingMonitor.log_checkpoint` — checkpoint directories as artifacts, i.e. model weights. Off unless `RAVEN_TRAIN_TRACKING=on`; having `wandb` installed and importable is deliberately not enough, because a self-hosted install must not publish weights because of what happens to be in its environment |

The corpus itself never leaves through this path unless tracking is on: rows are held in a
process-global builder, and the builder drops any row not added with `consented=true` and runs
`redact_pii` over every row it keeps, before the tokenizer sees it.

## LAN and paired devices

| Host | Caller | What goes out |
|------|--------|---------------|
| *(built at runtime)* | `raven/cli/nodes_cmd.py:28` | `http://{device_id}:18789` — the address a paired node announced, so no label is fixed in the source. It is a LAN address of your own network, reachable only after you pair the device, and the mobile-node commands are the only caller |

## Strings, not sockets

A host written into help text or a public identifier is not a destination; these are named here so the
scan stays honest about what it found.

| Host | Where | Why it is not egress |
|------|-------|----------------------|
| `t.me` | `raven/cli/onboard.py` | a link printed for the user to open |
| `git-scm.com` | `raven/plugins/git/plugin.py` | text inside a "git not found" message |
| `www.apple.com` | `raven/cli/service.py` | the public DTD identifier of a launchd plist; nothing fetches it |
| `registry.example.com` | `ravencode/runtime/tools/definitions.py` | a placeholder inside a documented example |
| `localhost` | 18 modules | loopback only: the gateway's own port, Ollama, LM Studio, the Signal daemon |

## What never leaves

- **No Raven-operated service.** There is no update check, no crash reporter, no analytics beacon and
  no license ping: no code path names a host this project runs. Distribution is PyPI, GHCR and GitHub
  Releases, pulled by the operator or by CI, not by the running process.
- **Telemetry is off by default** (`FeatureFlags.telemetry = False`, `raven/core/features.py`) and even
  when enabled it writes to the local database; the analytics and A/B routers serve read queries over
  the gateway's own authenticated HTTP surface.
- **The web UI loads nothing from a third-party host.** Inter and JetBrains Mono are vendored as woff2
  under `web/public/fonts/` (`web/src/styles/fonts.css`), the browser-extension popup ships its own
  CSS and JS (`extension/src/popup/`, with `script-src 'self'` pinned in the manifest), and the
  no-Node fallback page served by the gateway (`raven/channels/webchat/channel.py`) is a single
  document with no subresources. The test asserts all three carry no external `src`/`href`.
- **Provider keys, chats and embeddings stay on the machine**: `data/` for SQLite, `WORKSPACE_PATH`
  for files, and outbound calls carry only the prompt, query or message the feature was asked to send.
