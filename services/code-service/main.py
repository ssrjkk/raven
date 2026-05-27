from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time

import uvicorn
from fastapi import FastAPI, HTTPException
from loguru import logger

app = FastAPI(title="Code Service", version="1.0.0")
started_at = 0.0

ALLOWED_EXTENSIONS = {".py", ".js", ".ts", ".rs", ".go", ".java", ".cpp", ".h"}
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "30"))
MAX_OUTPUT_SIZE = 1024 * 100


@app.on_event("startup")
async def startup():
    global started_at
    started_at = time.time()
    logger.info("code-service started (timeout={}s, allowed={})", SANDBOX_TIMEOUT, ALLOWED_EXTENSIONS)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "code-service", "uptime": round(time.time() - started_at, 1)}


@app.get("/ready")
async def ready():
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    return {"uptime_seconds": round(time.time() - started_at, 1)}


@app.post("/api/v1/code/execute")
async def execute_code(request: dict):
    code = request.get("code", "")
    language = request.get("language", "python").lower()
    runner = {
        "python": ["python3", "-c", code],
        "python3": ["python3", "-c", code],
        "js": ["node", "-e", code],
        "node": ["node", "-e", code],
    }.get(language)

    if not runner:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")

    with tempfile.TemporaryDirectory() as tmpdir:
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *runner,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmpdir,
                env={"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": tmpdir},
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=SANDBOX_TIMEOUT
                )
                elapsed = time.monotonic() - start
                return {
                    "stdout": stdout.decode()[:MAX_OUTPUT_SIZE],
                    "stderr": stderr.decode()[:MAX_OUTPUT_SIZE],
                    "exit_code": proc.returncode,
                    "duration_ms": round(elapsed * 1000),
                }
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("Code execution timed out ({}s): {}", SANDBOX_TIMEOUT, code[:80])
                raise HTTPException(status_code=408, detail="Execution timed out")
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Code execution error: {}", e)
            raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("SERVICE_PORT", "8006"))
    uvicorn.run(app, host="0.0.0.0", port=port)
