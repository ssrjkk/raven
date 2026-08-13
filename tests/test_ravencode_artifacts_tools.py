from __future__ import annotations

import json
from pathlib import Path

import pytest

from ravencode.runtime.agent_core import AgentConfig, AgentEvent, EventEmitter, ReActAgent
from ravencode.runtime.tools import MODULE_TOOLS, execute_tool


def test_create_artifact_registered() -> None:
    spec = MODULE_TOOLS.get("create_artifact")
    assert spec is not None
    assert spec["handler"].__name__ == "create_artifact"
    assert {"title", "artifact_type", "content"} <= set(spec["parameters"]["properties"])


@pytest.mark.asyncio
async def test_create_artifact_persists_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    raw = await execute_tool(
        "create_artifact",
        {
            "title": "Login Form",
            "artifact_type": "react",
            "content": "export default function Login() {}",
            "path": "components/Login.tsx",
        },
    )
    payload = json.loads(raw)
    assert payload["status"] == "created"
    assert payload["title"] == "Login Form"
    assert payload["type"] == "react"
    assert len(payload["artifact_id"]) == 8
    written = tmp_path / "components" / "Login.tsx"
    assert written.read_text(encoding="utf-8") == "export default function Login() {}"


@pytest.mark.asyncio
async def test_create_artifact_no_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    raw = await execute_tool(
        "create_artifact",
        {"title": "Diagram", "artifact_type": "mermaid", "content": "graph TD;\nA-->B;"},
    )
    payload = json.loads(raw)
    assert payload["status"] == "created"
    assert payload["file_path"] is None


@pytest.mark.asyncio
async def test_create_artifact_confined(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    raw = await execute_tool(
        "create_artifact",
        {"title": "Evil", "artifact_type": "html", "content": "x", "path": "../../escape.html"},
    )
    payload = json.loads(raw)
    assert "error" in payload


@pytest.mark.asyncio
async def test_create_artifact_rejects_bad_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    raw = await execute_tool(
        "create_artifact",
        {"title": "Bad", "artifact_type": "yaml", "content": "x"},
    )
    assert raw.startswith("[validation_error]")


@pytest.mark.asyncio
async def test_create_artifact_emits_artifact_created_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    ee = EventEmitter()
    events: list[AgentEvent] = []

    async def capture(event: AgentEvent) -> None:
        events.append(event)

    ee.on("artifact_created", capture)
    agent = ReActAgent(config=AgentConfig(proactive_scan=False, event_emitter=ee))

    first_call = True

    async def fake_llm(messages):
        nonlocal first_call
        if first_call:
            first_call = False
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "create_artifact",
                            "arguments": json.dumps(
                                {
                                    "title": "Login Form",
                                    "artifact_type": "react",
                                    "content": "export default function Login() {}",
                                    "path": "components/Login.tsx",
                                }
                            ),
                        },
                    }
                ],
            }
        return {"content": "done"}

    agent.llm_provider = fake_llm
    out = await agent.run("make a login form")
    assert out == "done"
    artifact_events = [e for e in events if e.type == "artifact_created"]
    assert len(artifact_events) == 1
    data = artifact_events[0].data
    assert data["title"] == "Login Form"
    assert data["type"] == "react"
    assert data["file_path"] == str(Path("components") / "Login.tsx")
    assert len(data["artifact_id"]) == 8


class TestMultimodalRun:
    @pytest.mark.asyncio
    async def test_run_with_images_builds_content_blocks(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        agent = ReActAgent(config=AgentConfig(proactive_scan=False))

        async def fake_llm(messages):
            return {"content": "ok"}

        agent.llm_provider = fake_llm
        out = await agent.run("what is this?", images=["data:image/png;base64,AAAA"])
        assert out == "ok"
        user = [m for m in agent.conversation.messages if m.get("role") == "user"][-1]
        assert isinstance(user["content"], list)
        assert user["content"][0] == {"type": "text", "text": "what is this?"}
        assert user["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}

    @pytest.mark.asyncio
    async def test_run_without_images_keeps_plain_string(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        agent = ReActAgent(config=AgentConfig(proactive_scan=False))

        async def fake_llm(messages):
            return {"content": "ok"}

        agent.llm_provider = fake_llm
        await agent.run("plain text")
        user = [m for m in agent.conversation.messages if m.get("role") == "user"][-1]
        assert user["content"] == "plain text"

    @pytest.mark.asyncio
    async def test_run_with_raw_base64_padded_as_png(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        agent = ReActAgent(config=AgentConfig(proactive_scan=False))

        async def fake_llm(messages):
            return {"content": "ok"}

        agent.llm_provider = fake_llm
        await agent.run("diagram", images=["QUJD"])
        user = [m for m in agent.conversation.messages if m.get("role") == "user"][-1]
        assert user["content"][1]["image_url"]["url"] == "data:image/png;base64,QUJD"
