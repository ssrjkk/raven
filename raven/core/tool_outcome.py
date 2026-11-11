"""What a finished tool call actually answered.

Handlers report their own failures as text, and the vocabulary is shared: `raven/tools/shell.py`
prefixes a policy refusal with `[denied]` and appends `[exit code: N]` to a failing command's output,
`raven/plugins/*/plugin.py` append the same exit-code marker, `raven/core/plugin_loader.py` and the
MCP bridge answer `[error] ...`, and several tools reply with a dict carrying an `error` key
(`raven/tools/github.py` does it for every unauthenticated call). Before this module each consumer
read part of that vocabulary and none read the rest: the agent flattened every value into
`{"result": str(result)[:4000]}` and looked for an `error` key on the flattened envelope, so a
refusal printed `[shell.run → ok]` and the model recorded the same success; the task engine only
knew `[error]`, so a denied step was a passed step.

Classify the handler's own value, before truncation: a failing command that floods the output cap
carries its marker off the end of the string, and the status would be lost with it.
"""

from __future__ import annotations

import re

DENIED_PREFIX = "[denied]"
ERROR_PREFIX = "[error]"
TIMEOUT_PREFIX = "[timeout"
EXIT_CODE_RE = re.compile(r"\[exit code: (-?\d+)\]$")


def failure_detail(result: object) -> str | None:
    """Why this answer did not succeed, or None when it did."""
    if isinstance(result, dict):
        error = result.get("error")
        if error:
            return str(error)
        if result.get("success") is False:
            return "the tool reported success=False"
        return None
    text = str(result)
    if text.startswith((DENIED_PREFIX, ERROR_PREFIX, TIMEOUT_PREFIX)):
        return text
    match = EXIT_CODE_RE.search(text.rstrip("\n"))
    if match and match.group(1) != "0":
        return f"command exited with code {match.group(1)}"
    return None
