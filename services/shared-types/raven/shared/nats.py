from __future__ import annotations

NATS_SUBJECTS = {
    # Message flow
    "MESSAGE_INBOUND": "messages.inbound.{channel}",
    "MESSAGE_INBOUND_ALL": "messages.inbound.>",
    "AGENT_RESPONSE": "agent.responses.{session_id}",
    "AGENT_RESPONSE_ALL": "agent.responses.>",
    # Monitor flow
    "MONITOR_CHECK_RESULT": "monitor.checks.{monitor_id}",
    "MONITOR_ALERT": "monitor.alerts.{monitor_id}",
    # Domain events (SAGA)
    "EVENT_USER_REGISTERED": "events.auth.user.registered",
    "EVENT_TASK_PLANNED": "events.task.planned",
    "EVENT_TASK_COMPLETED": "events.task.completed",
    "EVENT_ROUTINE_TRIGGERED": "events.routine.triggered",
    # Audit
    "AUDIT_LOG": "audit.log.{service}",
}

# Durable consumer groups
NATS_CONSUMER_GROUPS = {
    "gateway": {
        "MESSAGE_INBOUND_ALL": "gateway-agent-workers",
        "AGENT_RESPONSE_ALL": "gateway-feedback",
    },
    "agent-core": {
        "MESSAGE_INBOUND_ALL": "agent-core-workers",
    },
    "monitor-engine": {
        "MONITOR_ALERT": "monitor-alert-handlers",
    },
    "audit-logger": {
        "AUDIT_LOG": "audit-consumers",
    },
}
