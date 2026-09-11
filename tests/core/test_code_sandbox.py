from __future__ import annotations

import pytest

from raven.core.sandbox import SandboxConfig, _validate_ast
from raven.core.security.code_sandbox import DENIED_BUILTINS, DENIED_MODULES, validate_python_code
from raven.tools._pyrunner import run as pyrunner_run


class TestValidatePythonCode:
    def test_safe_code_passes(self) -> None:
        assert validate_python_code("1 + 1") is None
        assert validate_python_code("name = 'world'; out = f'hello {name}'") is None

    def test_dangerous_builtins_blocked(self) -> None:
        assert validate_python_code("eval('1+1')") is not None
        assert validate_python_code("open('x')") is not None
        assert validate_python_code("format(())") is not None
        assert validate_python_code("'{0.__class__.__mro__}'.format(())") is not None

    def test_dunder_escape_blocked(self) -> None:
        assert validate_python_code("f'{().__class__}'") is not None
        assert validate_python_code("().__class__.__bases__[0].__subclasses__()") is not None
        assert validate_python_code("print('__globals__')") is not None

    def test_from_import_cannot_import_denied_module(self) -> None:
        assert validate_python_code("from os import system; system('id')") is not None
        assert validate_python_code("from pathlib import Path; Path('.')") is not None

    def test_denied_modules_cover_io_surfaces(self) -> None:
        for mod in ("pathlib", "io", "urllib", "asyncio", "http", "multiprocessing", "threading", "sqlite3"):
            assert mod in DENIED_MODULES, f"{mod} must be denied"
            assert validate_python_code(f"import {mod}") is not None
            assert validate_python_code(f"from {mod} import something") is not None

    def test_attribute_call_on_denied_module(self) -> None:
        assert "os" in DENIED_MODULES
        assert validate_python_code("os.system('ls')") is not None
        assert validate_python_code("urllib.request.urlopen('http://x')") is not None

    def test_denied_builtins_set_is_shared(self) -> None:
        assert "open" in DENIED_BUILTINS
        assert "getattr" in DENIED_BUILTINS

    def test_syntax_error_returns_message(self) -> None:
        assert "Syntax" in (validate_python_code("def broken(") or "")


class TestPyrunner:
    def test_safe_code_executes(self) -> None:
        assert "2" in pyrunner_run("1 + 1")
        assert "hello" in pyrunner_run("'he' + 'llo'")

    def test_import_escape_blocked(self) -> None:
        for code in (
            "import os; os.system('echo pwned')",
            "from os import system; system('echo pwned')",
            "import pathlib; pathlib.Path('.')",
            "from urllib import request; request.urlopen('http://127.0.0.1')",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1')",
            "import asyncio; asyncio.run(asyncio.sleep(0))",
            "import io; io.open('/tmp/x')",
            "import threading; threading.Thread()",
            "import multiprocessing; multiprocessing.Process()",
            "import sqlite3; sqlite3.connect(':memory:')",
        ):
            assert "[denied]" in pyrunner_run(code), code

    def test_dunder_escape_blocked(self) -> None:
        assert "[denied]" in pyrunner_run("().__class__.__mro__")
        assert "[denied]" in pyrunner_run("print('__globals__')")

    def test_dangerous_builtin_blocked(self) -> None:
        assert "[denied]" in pyrunner_run("eval('1+1')")


class TestSandboxAst:
    def test_sandbox_now_blocks_io_modules(self) -> None:
        assert _validate_ast("import pathlib") is not None
        assert _validate_ast("import io") is not None
        assert _validate_ast("import urllib") is not None
        assert _validate_ast("import asyncio") is not None
        assert _validate_ast("from os import system") is not None
        assert _validate_ast("os.system('id')") is not None

    def test_sandbox_still_allows_safe_code(self) -> None:
        assert _validate_ast("print(1 + 1)") is None

    @pytest.mark.asyncio
    async def test_sandbox_direct_exec_blocks_escape(self) -> None:
        sandbox = _make_direct_sandbox()
        out = await sandbox.exec("import pathlib; pathlib.Path('.')")
        assert "[denied]" in out


def _make_direct_sandbox():
    from raven.core.sandbox import Sandbox

    return Sandbox(SandboxConfig(mode="none"))
