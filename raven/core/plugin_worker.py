from __future__ import annotations

import asyncio
import builtins
import inspect
import json
import sys
import threading
from types import ModuleType
from typing import Any

from loguru import logger

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

# Modules a plugin may import. Everything that can reach a file, a socket or a process is absent on
# purpose — a plugin that needs those asks the host for a capability instead. The plugin API is on the
# list because `register()` has to name the class the protocol expects, but it is answered by the shim
# below rather than by the host module. `__future__` is a compile-time directive over the plugin's own
# file and imports no capability; without it the example the guide tells an operator to copy
# (`plugins/example-http`, which starts `from __future__ import annotations`) was refused at registration.
_SAFE_IMPORTS = frozenset(
    {
        "ravencode.runtime.plugins",
        "__future__",
        "base64",
        "binascii",
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "hashlib",
        "hmac",
        "itertools",
        "json",
        "math",
        "re",
        "statistics",
        "string",
        "textwrap",
        "time",
        "typing",
        "unicodedata",
        "uuid",
        "urllib.parse",
        "zoneinfo",
    }
)

_REAL_IMPORT = builtins.__import__


# The plugin-facing API, served to plugin code as `ravencode.runtime.plugins`. It cannot be the real
# module: `Plugin.__init__.__globals__` is the host module's namespace, and that one attribute gave a
# plugin `Path`, `asyncio` and `logger` — measured on the tree, a 10-line plugin read
# `data/web_secret_key` through it without importing anything. Here the class is exec'd into a
# namespace this file builds, so the only names reachable from it are the restricted builtins.
_PLUGIN_API_SOURCE = '''
class Plugin:
    """What `register()` returns: a name, a version and the tools this plugin publishes."""

    def __init__(self, name, version="0.1.0", tools=None, on_load=None, on_unload=None, _source_path=None):
        self.name = name
        self.version = version
        self.tools = tools or {}
        self._on_load = on_load
        self._on_unload = on_unload
        self._source_path = _source_path

    def load(self):
        if self._on_load:
            self._on_load()

    def unload(self):
        if self._on_unload:
            self._on_unload()
'''

_PLUGIN_API_NAME = "ravencode.runtime.plugins"
_plugin_api: ModuleType | None = None


def _plugin_api_module() -> ModuleType:
    global _plugin_api
    if _plugin_api is None:
        namespace: dict[str, Any] = {}
        exec(_PLUGIN_API_SOURCE, namespace)  # compiles a source constant kept in this file, never code that came from a plugin  # nosec B102
        # swapped in after the class exists: defining a class needs `__build_class__`, but what a plugin
        # can reach is this dict as it is later, through `Plugin.__init__.__globals__`.
        namespace["__builtins__"] = _restricted_builtins()
        module = ModuleType(_PLUGIN_API_NAME)
        module.__dict__.update({k: v for k, v in namespace.items() if not k.startswith("__")})
        _plugin_api = module
    return _plugin_api


def _guarded_import(
    name: str,
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    if level:
        msg = f"plugin import of {name!r} is blocked: relative imports have no package to resolve against"
        raise ImportError(msg)
    if name == _PLUGIN_API_NAME:
        return _plugin_api_module()
    if name not in _SAFE_IMPORTS:
        msg = f"plugin import of {name!r} is blocked - a plugin may import only {', '.join(sorted(_SAFE_IMPORTS))}"
        raise ImportError(msg)
    return _REAL_IMPORT(name, globals, locals, fromlist, level)


# Per-plugin restricted builtins namespace. Injected into each plugin module's
# __builtins__ (NOT the process-global builtins) so untrusted plugin code cannot
# reach open()/exec/eval/getattr etc. while leaving the worker's own
# runtime completely intact. Mutating the global builtins module here would
# corrupt the worker's own lazy imports (importlib.util, pathlib, ...).
# `__import__` is present but guarded, because with no import at all a plugin cannot name Plugin.
def _restricted_builtins() -> dict[str, Any]:
    try:
        import builtins as _b
    except Exception:
        logger.debug("[plugin_worker] failed to import builtins")
        return {"__import__": _guarded_import}
    allowed = {name: getattr(_b, name) for name in _BUILTINS_ALLOWLIST if hasattr(_b, name)}
    allowed["__import__"] = _guarded_import
    return allowed



def _apply_module_sandbox(mod: Any) -> None:
    mod.__dict__["__builtins__"] = _restricted_builtins()


_cap_futures: dict[str, asyncio.Future[Any]] = {}
_bg_tasks: set[asyncio.Task[None]] = set()


class PluginContext:
    def __init__(self, plugin_name: str) -> None:
        self._plugin_name = plugin_name

    async def _request_capability(self, capability: str, **args: Any) -> Any:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
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


def _pump_stdin(loop: asyncio.AbstractEventLoop) -> None:
    """Read one JSON command per line and hand it to the loop, from a thread.

    `loop.connect_read_pipe(sys.stdin)` cannot be used here: `sys.stdin` is a text wrapper, and on
    Windows the proactor read pipe transport dies with an internal AttributeError before any command
    is answered, so every plugin registration failed with a closed connection. A blocking read in a
    daemon thread needs no event-loop support at all, and the loop stays free to await capability
    round-trips that arrive on the very same pipe.
    """
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "capability_response":
            loop.call_soon_threadsafe(_deliver_capability_response, raw)
        else:
            loop.call_soon_threadsafe(_start_command, loop, msg)
    loop.call_soon_threadsafe(loop.stop)


def _start_command(loop: asyncio.AbstractEventLoop, cmd: dict[str, Any]) -> None:
    task = loop.create_task(_handle_command(cmd))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


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
        logger.debug("[plugin_worker] command handler error: {}", e)
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
    _apply_module_sandbox(mod)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "register"):
        return {"type": "error", "error": "no register() function"}
    with_timeout = cmd.get("register_timeout", 2.0)
    try:
        plugin = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
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
        logger.debug("[plugin_worker] register failed: {}", e)
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
    _apply_module_sandbox(mod)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "register"):
        return {"type": "error", "error": "no register() function"}
    ctx = PluginContext(path.parent.name)
    try:
        plugin = _call_register(mod, ctx)
    except Exception as e:
        logger.debug("[plugin_worker] tool call register() failed: {}", e)
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
        logger.debug("[plugin_worker] tool {} failed: {}", cmd.get("tool", "?"), e)
        return {"type": "error", "error": str(e)}


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    threading.Thread(target=_pump_stdin, args=(loop,), daemon=True).start()
    try:
        loop.run_forever()
    finally:
        pending = [t for t in _bg_tasks if not t.done()]
        for task in pending:
            task.cancel()
        loop.close()


if __name__ == "__main__":
    main()
