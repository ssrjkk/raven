from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from raven.core.llm.providers.bedrock import BedrockProvider
from raven.core.llm.providers.copilot import CopilotProvider
from raven.core.llm.providers.vertex import VertexAIProvider


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _StreamResp:
    def __init__(self, lines) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _StreamCM:
    def __init__(self, lines) -> None:
        self._lines = lines

    async def __aenter__(self) -> _StreamResp:
        return _StreamResp(self._lines)

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeClient:
    def __init__(self, post_payload=None, stream_lines=None, post_error=None) -> None:
        self._post_payload = post_payload
        self._stream_lines = stream_lines or []
        self._post_error = post_error
        self.closed = False
        self.post_calls: list[dict[str, Any]] = []

    async def post(self, url, json=None, headers=None):
        self.post_calls.append({"url": url, "json": json, "headers": headers})
        if self._post_error is not None:
            raise self._post_error
        return _FakeResponse(self._post_payload)

    def stream(self, method, url, json=None, headers=None):
        return _StreamCM(self._stream_lines)

    async def aclose(self) -> None:
        self.closed = True


async def _collect(agen):
    return [tok async for tok in agen]


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------

def test_copilot_static_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COPILOT_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider(api_key="sk-static")
    assert p._static is True


@pytest.mark.asyncio
async def test_copilot_get_token_static_returns_without_http(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider(api_key="sk-static")
    assert await p._get_token() == "sk-static"
    assert client.post_calls == []


@pytest.mark.asyncio
async def test_copilot_get_token_exchanges_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COPILOT_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-pat")
    client = _FakeClient(post_payload={"token": "short-lived"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider()
    assert p._static is False
    assert await p._get_token() == "short-lived"
    assert client.post_calls[0]["headers"]["Authorization"] == "Bearer gh-pat"


@pytest.mark.asyncio
async def test_copilot_get_token_without_any_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COPILOT_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider()
    assert await p._get_token() == ""


@pytest.mark.asyncio
async def test_copilot_get_token_falls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COPILOT_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-pat")
    client = _FakeClient(post_error=RuntimeError("network down"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider()
    assert await p._get_token() == "gh-pat"  # falls back to github token
    assert p._token_expires_at == 0.0


@pytest.mark.asyncio
async def test_copilot_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"choices": [{"message": {"content": "Hi there"}, "finish_reason": "stop"}], "usage": {"total_tokens": 3}}
    client = _FakeClient(post_payload=payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider(api_key="k")
    resp = await p.complete([{"role": "user", "content": "hello"}], "copilot/gpt-4")
    assert resp.content == "Hi there"
    assert resp.finish_reason == "stop"
    assert client.post_calls[0]["json"]["model"] == "gpt-4"  # prefix stripped


@pytest.mark.asyncio
async def test_copilot_complete_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: {not-json",
        "ignore me",
        "data: [DONE]",
    ]
    client = _FakeClient(stream_lines=lines)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider(api_key="k")
    tokens = await _collect(p.complete_stream([{"role": "user", "content": "x"}], "copilot/gpt-4"))
    assert "".join(tokens) == "Hello"


@pytest.mark.asyncio
async def test_copilot_complete_with_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"choices": [{"message": {"content": "ok"}, "finish_reason": "tool_calls"}]}
    client = _FakeClient(post_payload=payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider(api_key="k")
    tools = [{"type": "function", "function": {"name": "x"}}]
    resp = await p.complete([{"role": "user", "content": "hi"}], "copilot/gpt-4", tools=tools)
    assert resp.content == "ok"
    assert client.post_calls[0]["json"]["tools"] == tools


@pytest.mark.asyncio
async def test_copilot_complete_stream_with_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = ['data: {"choices":[{"delta":{"content":"y"}}]}', "data: [DONE]"]
    client = _FakeClient(stream_lines=lines)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider(api_key="k")
    tokens = await _collect(p.complete_stream([{"role": "user", "content": "x"}], "copilot/gpt-4", tools=[{"name": "t"}]))
    assert tokens == ["y"]


@pytest.mark.asyncio
async def test_copilot_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = CopilotProvider(api_key="k")
    await p.cleanup()
    assert client.closed and p._token is None


# ---------------------------------------------------------------------------
# Vertex
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, out=b"VT-TOKEN\n", err=b"", rc: int = 0) -> None:
        self._out = out
        self._err = err
        self.returncode = rc
        self.killed = False

    async def communicate(self):
        return self._out, self._err

    def kill(self) -> None:
        self.killed = True


@pytest.mark.asyncio
async def test_vertex_token_from_gcloud_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    exec_mock = AsyncMock(return_value=_FakeProc(out=b"VT-TOKEN\n"))
    monkeypatch.setattr("raven.core.llm.providers.vertex.asyncio.create_subprocess_exec", exec_mock)
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj")
    assert await p._get_token() == "VT-TOKEN"
    assert await p._get_token() == "VT-TOKEN"
    assert exec_mock.await_count == 1


@pytest.mark.asyncio
async def test_vertex_token_falls_back_to_creds_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "raven.core.llm.providers.vertex.asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError("no gcloud"))
    )
    creds = tmp_path / "creds.json"
    creds.write_text('{"access_token": "AT-FROM-FILE"}')
    monkeypatch.setenv("VERTEX_AI_CREDENTIALS", str(creds))
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj")
    assert await p._get_token() == "AT-FROM-FILE"
    # from-creds tokens are returned verbatim on the next call, no subprocess
    assert await p._get_token() == "AT-FROM-FILE"


@pytest.mark.asyncio
async def test_vertex_gcloud_nonzero_rc_then_no_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.llm.providers.vertex.asyncio.create_subprocess_exec", AsyncMock(return_value=_FakeProc(rc=1, err=b"unauth"))
    )
    monkeypatch.delenv("VERTEX_AI_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj")
    assert await p._get_token() == ""


@pytest.mark.asyncio
async def test_vertex_service_account_without_access_token(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "raven.core.llm.providers.vertex.asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)
    )
    creds = tmp_path / "sa.json"
    creds.write_text('{"private_key": "abc"}')
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj")
    assert await p._get_token() == ""


@pytest.mark.asyncio
async def test_vertex_creds_file_read_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "raven.core.llm.providers.vertex.asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)
    )
    monkeypatch.setenv("VERTEX_AI_CREDENTIALS", str(tmp_path / "missing.json"))
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj")
    assert await p._get_token() == ""


@pytest.mark.asyncio
async def test_vertex_gcloud_timeout_kills_process(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc()
    monkeypatch.setattr(
        "raven.core.llm.providers.vertex.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
    )

    async def _raise_timeout(coro, *a, **k):
        # real wait_for wraps the coroutine; close it so it is not left un-awaited
        if hasattr(coro, "close"):
            coro.close()
        raise TimeoutError

    monkeypatch.setattr("raven.core.llm.providers.vertex.asyncio.wait_for", _raise_timeout)
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj")
    with pytest.raises(TimeoutError):
        await p._get_token()
    assert proc.killed is True


def test_vertex_model_id() -> None:
    p = VertexAIProvider.__new__(VertexAIProvider)
    assert p._model_id("vertex/gemini-1.5") == "gemini-1.5"
    assert p._model_id("gemini-pro") == "gemini-pro"
@pytest.mark.asyncio
async def test_vertex_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": "Hello "}, {"text": "world"}]}}]}
    client = _FakeClient(post_payload=payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj", location="eu")
    monkeypatch.setattr(p, "_get_token", AsyncMock(return_value="t"))
    resp = await p.complete([{"role": "user", "content": "hi"}], "vertex/gemini-1.5")
    assert resp.content == "Hello world"
    assert resp.finish_reason == "stop"
    assert "eu-aiplatform" in client.post_calls[0]["url"]


@pytest.mark.asyncio
async def test_vertex_complete_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        '{"candidates":[{"content":{"parts":[{"text":"Hi"}]}}]}',
        "",
        "not-json-at-all",
        '{"candidates":[{"content":{"parts":[{}]}}]}',  # empty text → not yielded
    ]
    client = _FakeClient(stream_lines=lines)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj")
    monkeypatch.setattr(p, "_get_token", AsyncMock(return_value="t"))
    tokens = await _collect(p.complete_stream([{"role": "user", "content": "hi"}], "gemini-1.5"))
    assert tokens == ["Hi"]


@pytest.mark.asyncio
async def test_vertex_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = VertexAIProvider(project="prj")
    await p.cleanup()
    assert client.closed


# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bedrock_signed_headers_without_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = BedrockProvider(region="us-west-2", api_key="AK", secret_key="SK")
    headers = await p._signed_headers("POST", "https://bedrock-runtime.us-west-2.amazonaws.com/model/x/converse", b"{}")
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert "X-Amz-Security-Token" not in headers
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_bedrock_signed_headers_with_session_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = BedrockProvider(region="us-east-1", api_key="AK", secret_key="SK", session_token="SESS")
    headers = await p._signed_headers("POST", "https://bedrock-runtime.us-east-1.amazonaws.com/model/x/converse", b"{}")
    assert headers["X-Amz-Security-Token"] == "SESS"


def test_bedrock_model_id_and_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = BedrockProvider()
    assert p.region == "ap-south-1"
    assert p._model_id("bedrock/claude-v1") == "claude-v1"


@pytest.mark.asyncio
async def test_bedrock_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"output": {"message": {"content": [{"text": "A"}, {"text": "B"}, {"nope": 1}]}}, "stopReason": "end_turn"}
    client = _FakeClient(post_payload=payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = BedrockProvider(region="us-east-1", api_key="AK", secret_key="SK")
    resp = await p.complete(
        [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}], "bedrock/claude"
    )
    assert resp.content == "A B"
    assert resp.finish_reason == "end_turn"
    sent = client.post_calls[0]["json"]
    assert sent["system"] == [{"text": "be nice"}]
    assert sent["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]


@pytest.mark.asyncio
async def test_bedrock_complete_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        'data:{"contentBlockDelta":{"delta":{"text":"X"}}}',
        "no-prefix",
        "data:{bad json",
        'data:{"contentBlockDelta":{"delta":{"other":1}}}',  # no text → skipped
    ]
    client = _FakeClient(stream_lines=lines)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = BedrockProvider(region="us-east-1", api_key="AK", secret_key="SK")
    tokens = await _collect(p.complete_stream([{"role": "user", "content": "hi"}], "bedrock/claude"))
    assert tokens == ["X"]


@pytest.mark.asyncio
async def test_bedrock_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)
    p = BedrockProvider(region="us-east-1", api_key="AK", secret_key="SK")
    await p.cleanup()
    assert client.closed
