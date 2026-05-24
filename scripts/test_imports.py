"""CI import verification script."""
import sys
import importlib

sys.path.insert(0, ".")

MODULES = [
    "raven.core.config",
    "raven.core.llm",
    "raven.core.db",
    "raven.core.agent.agent",
    "raven.core.agent.registry",
    "raven.core.gateway.gateway",
    "raven.core.task_engine.planner",
    "raven.core.coder.session",
    "raven.core.coder.review",
    "raven.core.sandbox",
    "raven.core.rag.retriever",
    "aios.api.bridge",
    "aios.agents.orchestrator",
    "aios.runtime.adapter",
    "ravencode",
    "ravencode.api.client",
    "ravencode.agents.orchestrator",
    "ravencode.runtime.shell",
]

failed = []
for mod in MODULES:
    try:
        importlib.import_module(mod)
        print(f"  OK  {mod}")
    except Exception as e:
        failed.append(f"  FAIL {mod}: {e}")
        print(f"  FAIL {mod}: {e}")

if failed:
    print(f"\n{len(failed)} module(s) failed to import")
    sys.exit(1)
else:
    print(f"\nAll {len(MODULES)} modules imported successfully")
