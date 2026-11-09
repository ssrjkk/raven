"""What the plugin loader puts in front of the model, measured against what the source says.

Measured before the fix, over the shipped `raven/plugins/` tree:

* 46 tools were published and 3 of them were not written by any plugin: `inspect.getmembers` returns
  coroutines the module *imported*, so `api.safe_fetch_async` and `browser.safe_fetch_async` were the
  SSRF helper (raven/core/security/ssrf.py:237) offered as tools, and `memory.run_python` was the code
  plugin's `run_python` imported under an alias (raven/plugins/memory/plugin.py:8). Each carried a
  name no operator had written down and no policy rule addressed.
* 2 of the 46 marked `**kwargs` as a required argument, because `inspect.Parameter.empty` is also the
  default of a VAR_KEYWORD slot (raven/core/plugin_loader.py:211 before the fix). A JSON tool call
  cannot fill that slot at all.
* 23 of the 46 had no docstring, so the description sent to the model was the bare function name
  ("http_get"), and 19 tools published parameters with no description.
* 1 tool, `cron.register_callback`, asked for a Python callable in a JSON field: a model could only
  pass a string, and a string awaited as a callback raises on every later trigger
  (raven/plugins/cron/plugin.py:28). It is an ordinary function now, so the loader does not publish
  it and host code can still bind a real coroutine.
* the parameter extractor read only the line starting with the parameter name, so any description
  wrapped onto a second line was cut and any sentence that merely began with that word was read as
  its description.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from raven.core.config import settings
from raven.core.plugin_loader import PluginLoader, _published_by_this_plugin, func_to_tool
from raven.core.security.ssrf import is_private_url

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "raven" / "plugins"

# the three handlers the loader used to publish from plugin.py's imports
PHANTOMS = ("api.safe_fetch_async", "browser.safe_fetch_async", "memory.run_python")
# the host hook that cannot be called from JSON: its one argument is a coroutine
HOST_ONLY = ("cron.register_callback",)
# tools whose shipped description is the minimum: the name said nothing, the model guessed
MIN_DESCRIPTION_CHARS = 25
# measured on the fixed tree; a drift here is a change to what the model can ask for
SHIPPED_TOOL_COUNT = 42


def _load_shipped() -> PluginLoader:
    loader = PluginLoader()
    for plugin_dir in sorted(PLUGIN_DIR.iterdir()):
        if plugin_dir.is_dir() and (plugin_dir / "plugin.py").exists():
            loader.load_from_dir(plugin_dir)
    return loader


@pytest.fixture(scope="module")
def shipped() -> dict[str, Any]:
    loader = _load_shipped()
    tools = loader.tools
    return {
        "loader": loader,
        "tools": tools,
        "names": {t.name for t in tools},
        "specs": [(t.name, t.description, t.parameters) for t in tools],
    }


def _write_plugin(tmp_path: Path, source: str, name: str = "probe") -> Path:
    plugin_dir = tmp_path / name
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_bytes(textwrap.dedent(source).encode("utf-8"))
    return plugin_dir


def _helpers_module(tmp_path: Path) -> Path:
    """A module outside the plugin directory exporting one coroutine, the way the SSRF layer does."""
    (tmp_path / "helperlib.py").write_bytes(
        b"async def imported_helper(url: str) -> str:\n    return url\n"
    )
    return tmp_path


# --- what the loader publishes ---------------------------------------------------------------


def test_no_imported_coroutine_reaches_the_surface(shipped: dict[str, Any]) -> None:
    for name in PHANTOMS:
        assert name not in shipped["names"], name


def test_no_host_only_hook_reaches_the_surface(shipped: dict[str, Any]) -> None:
    for name in HOST_ONLY:
        assert name not in shipped["names"], name


def test_every_published_handler_is_written_by_the_plugin_that_publishes_it(shipped: dict[str, Any]) -> None:
    for tool in shipped["tools"]:
        namespace, _, _ = tool.name.partition(".")
        plugin_file = PLUGIN_DIR / namespace / "plugin.py"
        assert tool.handler.__module__ == namespace, tool.name
        assert Path(inspect.getsourcefile(tool.handler) or "").resolve() == plugin_file.resolve(), tool.name


def test_the_published_count_is_the_measured_one(shipped: dict[str, Any]) -> None:
    assert len(shipped["tools"]) == SHIPPED_TOOL_COUNT, sorted(shipped["names"])


def test_an_imported_and_an_aliased_coroutine_are_not_published(tmp_path: Path) -> None:
    helpers = _helpers_module(tmp_path)
    sys.path.insert(0, str(helpers))
    try:
        plugin_dir = _write_plugin(
            tmp_path,
            '''
            from helperlib import imported_helper

            async def local(url: str) -> str:
                """A tool written here."""
                return url

            alias = local
            ''',
        )
        loader = PluginLoader()
        names = {t.name for t in loader.load_from_dir(plugin_dir)}
    finally:
        sys.path.remove(str(helpers))
        sys.modules.pop("helperlib", None)
    assert names == {"probe.local"}, names


def test_the_publishing_rule_itself() -> None:
    async def local(url: str) -> str:
        return url

    module = inspect.getmodule(test_the_publishing_rule_itself)
    assert module is not None
    assert _published_by_this_plugin(module, "local", local)
    assert not _published_by_this_plugin(module, "local_function", local)
    assert not _published_by_this_plugin(module, "local", asyncio.sleep)


def test_the_source_of_the_rule_is_the_helper() -> None:
    tree = ast.parse((ROOT / "raven" / "core" / "plugin_loader.py").read_text(encoding="utf-8"))
    body = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "load_from_dir")
    assert "_published_by_this_plugin" in ast.unparse(body), ast.unparse(body)[:400]


def test_a_tool_that_shows_the_model_only_its_name_is_warned_about(tmp_path: Path) -> None:
    """23 of the 46 shipped tools did exactly this; an operator has to be able to see it in the log."""
    from loguru import logger

    plugin_dir = _write_plugin(
        tmp_path,
        '''
        async def undocumented(url: str) -> str:
            return url
        ''',
    )
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING")
    try:
        tool = PluginLoader().load_from_dir(plugin_dir)[0]
    finally:
        logger.remove(sink_id)
    assert tool.description == "undocumented", tool.description
    assert [line for line in records if "probe.undocumented" in line and "docstring" in line], records


# --- parameter schemas ------------------------------------------------------------------------


def test_var_positional_and_var_keyword_are_never_required(tmp_path: Path) -> None:
    plugin_dir = _write_plugin(
        tmp_path,
        '''
        async def grab(url: str, *args, **kwargs) -> str:
            """Take anything."""
            return url
        ''',
    )
    tool = PluginLoader().load_from_dir(plugin_dir)[0]
    assert tool.parameters["required"] == ["url"], tool.parameters
    assert set(tool.parameters["properties"]) == {"url", "args", "kwargs"}, tool.parameters


def test_a_wrapped_parameter_description_is_kept_whole() -> None:
    async def fetch(url: str) -> str:
        """Fetch one page.

        url: the address to read, and this part of the explanation carries on
            past the end of the first line on purpose.
        """
        return url

    tool = func_to_tool(fetch)
    description = tool.parameters["properties"]["url"]["description"]
    assert description.startswith("the address to read")
    assert "past the end of the first line on purpose." in description, description


def test_a_section_header_does_not_become_a_parameter_description() -> None:
    async def fetch(url: str) -> str:
        """Fetch one page.

        url: the address to read.
        Returns:
            whatever the page said
        """
        return url

    tool = func_to_tool(fetch)
    description = tool.parameters["properties"]["url"]["description"]
    assert "Returns" not in description, description


def test_a_sentence_that_only_starts_with_the_parameter_name_is_not_its_description() -> None:
    async def fetch(code: str) -> str:
        """Fetch one page.

        code is a fine word to start a sentence with, and this is not a parameter line.
        """
        return code

    tool = func_to_tool(fetch)
    assert "description" not in tool.parameters["properties"]["code"], tool.parameters


def test_the_legacy_inline_args_form_still_describes_the_tool() -> None:
    async def legacy(path: str) -> str:
        """Say what it does. Args: path (str): Where to look"""
        return path

    tool = func_to_tool(legacy)
    assert tool.description == "Say what it does.", tool.description


def test_the_extractor_source_uses_the_continuation_rule() -> None:
    tree = ast.parse((ROOT / "raven" / "core" / "plugin_loader.py").read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "_param_docs" in names, sorted(names)


# --- the shipped descriptions -----------------------------------------------------------------


def test_no_shipped_description_is_the_bare_name(shipped: dict[str, Any]) -> None:
    bare = [name for name, description, _ in shipped["specs"] if description.strip() == name.split(".")[-1]]
    assert bare == [], bare


def test_every_shipped_description_is_a_sentence(shipped: dict[str, Any]) -> None:
    thin = [
        (name, len(description))
        for name, description, _ in shipped["specs"]
        if len(description.strip()) < MIN_DESCRIPTION_CHARS
    ]
    assert thin == [], thin


def test_every_shipped_parameter_is_described(shipped: dict[str, Any]) -> None:
    missing = []
    for name, _, parameters in shipped["specs"]:
        for param, schema in parameters["properties"].items():
            if not schema.get("description"):
                missing.append(f"{name}.{param}")
    assert missing == [], missing


def test_a_missing_docstring_is_not_papered_over() -> None:
    """func_to_tool must not invent a description: an undocumented plugin function has to stay visible."""
    tool = func_to_tool(_undocumented)
    assert tool.description == "_undocumented", tool.description


async def _undocumented(value: str) -> str:
    return value


# --- egress: the documented transport is the only one on the surface ---------------------------


def test_no_plugin_fetches_through_an_unpinned_client(shipped: dict[str, Any]) -> None:
    """docs/security/overview.md section 10 promises every model-supplied URL is fetched pinned."""
    offenders = []
    for namespace in sorted({name.partition(".")[0] for name in shipped["names"]}):
        source = (PLUGIN_DIR / namespace / "plugin.py").read_text(encoding="utf-8")
        if "httpx.AsyncClient(" in source:
            offenders.append(namespace)
    assert offenders == [], offenders


async def test_ocr_url_refuses_a_private_address_without_fetching_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.plugins.ocr import plugin as ocr

    called: list[str] = []

    async def _spy(url: str, *args: Any, **kwargs: Any) -> Any:
        called.append(url)
        raise AssertionError("must not be reached")

    monkeypatch.setattr(ocr, "safe_fetch_async", _spy)
    monkeypatch.setattr(settings, "ghost_mode", False)
    for url in ("http://127.0.0.1/page.png", "http://169.254.169.254/latest/meta-data.png"):
        assert is_private_url(url), url
        result = await ocr.ocr_url(url)
        assert "blocked" in result.lower() or "invalid" in result.lower(), result
    assert called == [], called


async def test_search_goes_through_the_pinned_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.plugins.browser import plugin as browser

    seen: list[str] = []

    class _Response:
        text = (
            "<html><body><div class='result'><div class='result__title'>"
            "<a href='https://example.invalid'>T</a></div>"
            "<div class='result__snippet'>S</div></div></body></html>"
        )

        def raise_for_status(self) -> None:
            return None

    async def _fake_fetch(url: str, *args: Any, **kwargs: Any) -> _Response:
        seen.append(url)
        return _Response()

    monkeypatch.setattr(browser, "safe_fetch_async", _fake_fetch)
    out = await browser.search("raven")
    assert seen == ["https://html.duckduckgo.com/html/?q=raven"], seen
    assert "Search results for 'raven'" in out, out
