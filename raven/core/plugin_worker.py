from __future__ import annotations

import asyncio
import builtins as _builtins_module
import inspect
import json
import sys
from typing import Any

_BUILTINS_ALLOWLIST = frozenset(
    {
        "None",
        "True",
        "False",
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "bytearray",
        "list",
        "dict",
        "tuple",
        "set",
        "frozenset",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "AttributeError",
        "RuntimeError",
        "StopIteration",
        "KeyboardInterrupt",
        "EOFError",
        "len",
        "range",
        "enumerate",
        "zip",
        "map",
        "filter",
        "iter",
        "next",
        "min",
        "max",
        "sum",
        "any",
        "all",
        "sorted",
        "reversed",
        "slice",
        "isinstance",
        "issubclass",
        "hasattr",
        "abs",
        "pow",
        "round",
        "ord",
        "chr",
        "hex",
        "oct",
        "bin",
        "repr",
        "hash",
        "id",
        "print",
        "object",
        "property",
        "super",
        "staticmethod",
        "classmethod",
        "type",
    }
)

for _name in list(_builtins_module.__dict__):
    if _name not in _BUILTINS_ALLOWLIST:
        _builtins_module.__dict__[_name] = None


_cap_futures: dict[str, asyncio.Future[Any]] = {}
_bg_tasks: set[asyncio.Task[None]] = set()


class PluginContext:
    def __init__(self, plugin_name: str) -> None:
        self._plugin_name = plugin_name

    async def _request_capability(self, capability: str, **args: Any) -> Any:
        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        cid = f"cap_{id(fut)}"
        _cap_futures[cid] = fut
        try:
            sys.stdout.write(
                json.dumps(
                    {
                        "type": "capability",
                        "id": cid,
                        "capability": capability,
                        "plugin": self._plugin_name,
                        "args": args,
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            return await asyncio.wait_for(fut, timeout=60.0)
        finally:
            _cap_futures.pop(cid, None)

    async def safe_http(
        self, method: str, url: str, headers: dict[str, str] | None = None, body: str | None = None
    ) -> str:
        result = await self._request_capability("safe_http", method=method, url=url, headers=headers, body=body)
        return str(result) if result is not None else ""

    async def safe_file_read(self, path: str) -> str:
        result = await self._request_capability("safe_file_read", path=path)
        return str(result) if result is not None else ""

    async def safe_file_write(self, path: str, content: str) -> str:
        result = await self._request_capability("safe_file_write", path=path, content=content)
        return str(result) if result is not None else ""


def _deliver_capability_response(raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    if msg.get("type") != "capability_response":
        return
    cid = msg.get("id", "")
    fut = _cap_futures.get(cid)
    if fut is None or fut.done():
        return
    if "error" in msg:
        fut.set_exception(RuntimeError(msg["error"]))
    else:
        fut.set_result(msg.get("result"))


async def _background_stdin_reader() -> None:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    while True:
        try:
            line = await reader.readline()
        except EOFError:
            break
        if not line:
            break
        raw = line.decode("utf-8").strip()
        if not raw:
            continue
        try:
            cmd = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if cmd.get("type") == "capability_response":
            _deliver_capability_response(raw)
        else:
            bg_task = asyncio.create_task(_handle_command(cmd))
            _bg_tasks.add(bg_task)
            bg_task.add_done_callback(_bg_tasks.discard)


async def _handle_command(cmd: dict[str, Any]) -> None:
    try:
        ctype = cmd.get("type")
        if ctype == "register":
            resp = await _do_register(cmd)
        elif ctype == "call_tool":
            resp = await _do_call_tool(cmd)
        else:
            resp = {"type": "error", "error": f"unknown command: {ctype}"}
    except Exception as e:
        resp = {"type": "error", "error": str(e)}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()


def _call_register(mod: Any, ctx: Any = None) -> Any:
    sig = inspect.signature(mod.register)
    if "ctx" in sig.parameters:
        return mod.register(ctx=ctx) if ctx else mod.register()
    return mod.register()


async def _do_register(cmd: dict[str, Any]) -> dict[str, Any]:
    import importlib.util
    from pathlib import Path

    path = Path(cmd["path"])
    spec = importlib.util.spec_from_file_location(path.parent.name, str(path))
    if not spec or not spec.loader:
        return {"type": "error", "error": "cannot load spec"}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "register"):
        return {"type": "error", "error": "no register() function"}
    with_timeout = cmd.get("register_timeout", 2.0)
    try:
        plugin = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                _call_register,
                mod,
                PluginContext(path.parent.name),
            ),
            timeout=with_timeout,
        )
    except TimeoutError:
        return {"type": "error", "error": "register() timed out"}
    except Exception as e:
        return {"type": "error", "error": str(e)}
    tools_meta = []
    for tname, tdef in (plugin.tools or {}).items():
        tools_meta.append(
            {
                "name": tname,
                "dangerous": tdef.get("dangerous", False),
                "description": tdef.get("description", ""),
                "parameters": tdef.get("parameters", {}),
            }
        )
    return {"type": "register_ok", "tools": tools_meta}


async def _do_call_tool(cmd: dict[str, Any]) -> dict[str, Any]:
    import importlib.util
    from pathlib import Path

    path = Path(cmd["path"])
    spec = importlib.util.spec_from_file_location(path.parent.name, str(path))
    if not spec or not spec.loader:
        return {"type": "error", "error": "cannot load spec"}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "register"):
        return {"type": "error", "error": "no register() function"}
    ctx = PluginContext(path.parent.name)
    try:
        plugin = _call_register(mod, ctx)
    except Exception as e:
        return {"type": "error", "error": str(e)}
    tool_name = cmd["tool"]
    tdef = (plugin.tools or {}).get(tool_name)
    if not tdef:
        return {"type": "error", "error": f"unknown tool: {tool_name}"}
    handler = tdef.get("handler")
    if not handler:
        return {"type": "error", "error": f"tool {tool_name} has no handler"}
    args = cmd.get("args", {})
    tool_timeout = cmd.get("tool_timeout", 30.0)
    try:
        result = await asyncio.wait_for(handler(**args), timeout=tool_timeout)
        return {"type": "result", "result": result}
    except TimeoutError:
        return {"type": "error", "error": f"tool {tool_name} timed out after {tool_timeout}s"}
    except Exception as e:
        return {"type": "error", "error": str(e)}


def main() -> None:
    asyncio.run(_background_stdin_reader())


if __name__ == "__main__":
    main()
