# Architecture

## Overview

Raven AI uses a **Gateway** architecture pattern:

```
[Channel] → [Gateway] → [Agent] → [LLM Provider]
                                → [Tool Registry]
                                → [Plugin System]
```

## Components

### Gateway

The `Gateway` class (`raven/core/gateway/gateway.py`) is the central orchestrator:
- Receives `IncomingMessage` events from channels
- Routes messages to the appropriate agent
- Manages channel lifecycle (start/stop)
- Coordinates health checks and self-healing

### Channels

Channel adapters (`raven/channels/`) normalize platform-specific APIs into a common interface:
```python
class BaseChannel(ABC):
    async def connect(self) -> None
    async def disconnect(self) -> None
    async def send(self, session_id: str, message: Message) -> None
    async def on_message(self, handler: MessageHandler) -> None
```

### Agents

Agents (`raven/core/agent/`) manage LLM interactions:
- Build system prompts with workspace files (AGENTS.md, SOUL.md, TOOLS.md)
- Manage conversation history
- Route tool calls to the ToolRegistry
- Handle streaming responses

### Tool Registry

The `ToolRegistry` (`raven/core/task_engine/tool_registry.py`) maintains a catalog of callable tools:
- Registered with name, description, parameter schema, and handler
- Tools are exposed to the LLM as function-calling definitions
- Each call is traced via OpenTelemetry

### Security

The security layer (`raven/core/security/`) provides:
- `PolicyEngine` — rule-based policy evaluation
- `ToolPolicyEvaluator` — tool-level access control
- `SecurityAudit` — configuration and runtime auditing
- `PIIEngine` — PII detection and redaction
- `ContextFilter` — content visibility control

## Data Flow

```
1. User sends message on Telegram
2. TelegramChannel converts to IncomingMessage
3. Gateway.handle_message() processes the event
4. AgentRegistry routes to the correct agent
5. Agent builds prompt + calls LLM
6. LLM responds (text + optional tool calls)
7. Tool calls are executed via ToolRegistry
8. Response sent back through the channel
```
