from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time

import uvicorn
from fastapi import FastAPI, HTTPException
from loguru import logger

try:
    from opentelemetry_setup import setup_opentelemetry
except ImportError:
    def setup_opentelemetry(app=None, service_name=None): pass

app = FastAPI(title="Code Service", version="1.0.0")
setup_opentelemetry(app, service_name="code-service")
started_at = 0.0

ALLOWED_EXTENSIONS = {".py", ".js", ".ts", ".rs", ".go", ".java", ".cpp", ".h"}
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "30"))
MAX_OUTPUT_SIZE = 1024 * 100
NATS_URL = os.environ.get("NATS_URL", "")


@app.on_event("startup")
async def startup():
    global started_at
    started_at = time.time()
    logger.info(
        "code-service started (timeout={}s, allowed={})",
        SANDBOX_TIMEOUT,
        ALLOWED_EXTENSIONS,
    )


@app.on_event("shutdown")
async def shutdown():
    try:
        from opentelemetry import trace
        trace.get_tracer_provider().shutdown()
    except Exception:
        pass
    logger.info("code-service shutdown")


@app.get("/health", summary="Health check", description="Returns service health status and uptime")
async def health():
    return {
        "status": "healthy",
        "service": "code-service",
        "uptime": round(time.time() - started_at, 1),
    }


@app.get("/ready", summary="Readiness check", description="Returns 200 when the service is ready to accept requests")
async def ready():
    return {"status": "ready"}


@app.get("/metrics", summary="Metrics snapshot", description="Returns service uptime metrics")
async def metrics():
    return {"uptime_seconds": round(time.time() - started_at, 1)}


@app.post("/api/v1/code/execute", summary="Execute code", description="Executes code in a sandboxed environment with timeout. Supports Python, JavaScript, Bash.")
async def execute_code(request: dict):
    code = request.get("code", "")
    language = request.get("language", "python").lower()

    if not code.strip():
        raise HTTPException(status_code=400, detail="Empty code")

    supported = {"python", "python3", "js", "node", "bash", "sh"}
    if language not in supported:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")

    with tempfile.TemporaryDirectory() as tmpdir:
        ext_map = {"python": ".py", "python3": ".py", "js": ".js", "node": ".js", "bash": ".sh", "sh": ".sh"}
        ext = ext_map.get(language, ".txt")
        script_path = os.path.join(tmpdir, f"script{ext}")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        interpreter = {
            "python": ["python3", script_path],
            "python3": ["python3", script_path],
            "js": ["node", script_path],
            "node": ["node", script_path],
            "bash": ["bash", script_path],
            "sh": ["sh", script_path],
        }[language]

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *interpreter,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmpdir,
                env={"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": tmpdir},
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SANDBOX_TIMEOUT)
                elapsed = time.monotonic() - start
                logger.info(
                    "Code executed: lang={} exit={} dur={:.0f}ms",
                    language,
                    proc.returncode,
                    elapsed * 1000,
                )
                return {
                    "stdout": stdout.decode()[:MAX_OUTPUT_SIZE],
                    "stderr": stderr.decode()[:MAX_OUTPUT_SIZE],
                    "exit_code": proc.returncode,
                    "duration_ms": round(elapsed * 1000),
                }
            except TimeoutError:
                proc.kill()
                logger.warning("Code execution timed out ({}s): {}", SANDBOX_TIMEOUT, code[:80])
                raise HTTPException(status_code=408, detail="Execution timed out") from None
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Code execution error: {}", e)
            raise HTTPException(status_code=500, detail=str(e)) from e


def _import_module(name: str):
    import importlib, sys
    from pathlib import Path
    _svc = Path(__file__).parent
    if str(_svc) not in sys.path:
        sys.path.insert(0, str(_svc))
    return importlib.import_module(name)


@app.post("/api/v1/agent/run", summary="Run RavenCode agent", description="Executes a coding task using RavenCode agent with build/plan/general mode.")
async def agent_run(request: dict):
    _a = _import_module("agent")

    task = request.get("task", "")
    mode_str = request.get("mode", "build")
    workspace = request.get("workspace", ".")

    if not task.strip():
        raise HTTPException(status_code=400, detail="Empty task")

    try:
        mode = _a.AgentMode(mode_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode_str}. Use build, plan, or general")

    agent = _a.RavenCodeAgent(mode=mode, workspace=workspace)
    try:
        result = await agent.run(task)
        return {"response": result[:10000], "mode": mode.value}
    except Exception as e:
        logger.error("Agent run failed: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/context/index", summary="Index codebase", description="Index the codebase using AST parsing and embeddings.")
async def context_index(request: dict):
    _c = _import_module("context")

    workspace = request.get("workspace", ".")
    ctx = _c.CodebaseContext(workspace)
    try:
        stats = await ctx.index_codebase()
        return {"indexed": stats.get("files", 0), "chunks": stats.get("chunks", 0)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/context/search", summary="Search codebase", description="Semantic search across indexed codebase.")
async def context_search(request: dict):
    _c = _import_module("context")

    workspace = request.get("workspace", ".")
    query = request.get("query", "")
    top_k = request.get("top_k", 5)

    if not query.strip():
        raise HTTPException(status_code=400, detail="Empty query")

    ctx = _c.CodebaseContext(workspace)
    try:
        results = await ctx.search(query, top_k=top_k)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("SERVICE_PORT", "8006"))
    uvicorn.run(app, host="0.0.0.0", port=port)
