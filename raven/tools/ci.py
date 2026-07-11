from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any, cast

import httpx

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def _github_request(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return {"error": "GITHUB_TOKEN env var required"}
    url = f"https://api.github.com{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.request(method, url, headers=headers, json=body)
        if resp.status_code >= 400:
            return {"error": f"GitHub API {resp.status_code}: {resp.text[:200]}"}
        return cast("dict[str, Any]", resp.json())


async def _gitlab_request(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    token = os.environ.get("GITLAB_TOKEN", "")
    base_url = os.environ.get("GITLAB_URL", "https://gitlab.com")
    if not token:
        return {"error": "GITLAB_TOKEN env var required"}
    url = f"{base_url}/api/v4{path}"
    headers = {"PRIVATE-TOKEN": token}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.request(method, url, headers=headers, json=body)
        if resp.status_code >= 400:
            return {"error": f"GitLab API {resp.status_code}: {resp.text[:200]}"}
        return cast("dict[str, Any]", resp.json())


async def ci_list_workflows(owner: str = "", repo: str = "", provider: str = "github") -> str:
    if provider == "github":
        if not owner or not repo:
            return "owner and repo required for GitHub"
        data = await _github_request(f"/repos/{owner}/{repo}/actions/workflows")
        if "error" in data:
            return str(data["error"])
        workflows = data.get("workflows", []) or []
        if not workflows:
            return f"No workflows found for {owner}/{repo}"
        lines = [f"Workflows for {owner}/{repo}:\n"]
        for w in workflows[:20]:
            lines.append(f"  {w['name']} ({w['state']}) — {w['id']}")
        return "\n".join(lines)
    elif provider == "gitlab":
        pid = owner or repo
        if not pid:
            return "project ID or path required for GitLab"
        data = await _gitlab_request(f"/projects/{pid.replace('/', '%2F')}/pipelines")
        if isinstance(data, dict):
            if "error" in data:
                return str(data["error"])
            return f"Unexpected response: {str(data)[:200]}"
        pipelines: list[Any] = data if isinstance(data, list) else []
        if not pipelines:
            return f"No pipelines found for project {pid}"
        lines = [f"Pipelines for {pid}:\n"]
        for p in pipelines[:20]:
            lines.append(f"  #{p['id']} — {p['status']} ({p.get('ref', '')})")
        return "\n".join(lines)
    return f"Unknown provider: {provider}"


async def ci_run_workflow(workflow_id: str, owner: str = "", repo: str = "", ref: str = "main", inputs: str = "", provider: str = "github") -> str:
    if provider == "github":
        if not owner or not repo:
            return "owner and repo required for GitHub"
        payload: dict[str, Any] = {"ref": ref}
        if inputs:
            import json
            try:
                payload["inputs"] = json.loads(inputs)
            except json.JSONDecodeError:
                return f"Invalid JSON inputs: {inputs}"
        data = await _github_request(f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches", method="POST", body=payload)
        if isinstance(data, dict) and "error" in data:
            return str(data.get("error", ""))
        return f"Triggered workflow {workflow_id} on {ref}"
    return f"Run not supported for provider: {provider}"


async def ci_pipeline_status(pipeline_id: str, owner: str = "", repo: str = "", provider: str = "github") -> str:
    if provider == "github":
        if not owner or not repo:
            return "owner and repo required for GitHub"
        data = await _github_request(f"/repos/{owner}/{repo}/actions/runs/{pipeline_id}")
        if isinstance(data, dict) and "error" in data:
            return str(data.get("error", ""))
        return (
            f"Run #{data['run_number']}: {data['name']}\n"
            f"  Status: {data['status']}\n"
            f"  Conclusion: {data.get('conclusion', 'pending')}\n"
            f"  Branch: {data['head_branch']}\n"
            f"  Commit: {data['head_sha'][:8]}\n"
            f"  URL: {data['html_url']}"
        )
    elif provider == "gitlab":
        pid = owner or repo
        if not pid:
            return "project ID required for GitLab"
        data = await _gitlab_request(f"/projects/{pid.replace('/', '%2F')}/pipelines/{pipeline_id}")
        if isinstance(data, dict):
            if "error" in data:
                return str(data.get("error", ""))
            return (
                f"Pipeline #{data['id']}: {data.get('ref', '')}\n"
                f"  Status: {data['status']}\n"
                f"  SHA: {data.get('sha', '')[:8]}\n"
                f"  Web URL: {data.get('web_url', '')}"
            )
        return f"Unexpected response: {str(data)[:200]}"
    return f"Unknown provider: {provider}"


async def ci_list_runs(owner: str = "", repo: str = "", branch: str = "", status: str = "", provider: str = "github") -> str:
    if provider != "github":
        return f"List runs not supported for provider: {provider}"
    if not owner or not repo:
        return "owner and repo required"
    params = ""
    if branch:
        params += f"&branch={branch}"
    if status:
        params += f"&status={status}"
    data = await _github_request(f"/repos/{owner}/{repo}/actions/runs?per_page=10{params}")
    if isinstance(data, dict) and "error" in data:
        return str(data.get("error", ""))
    runs = data.get("workflow_runs", [])
    if not runs:
        return f"No runs found for {owner}/{repo}"
    lines = [f"Recent runs for {owner}/{repo}:\n"]
    for r in runs[:10]:
        lines.append(f"  #{r['run_number']} {r['name']} — {r['status']}/{r.get('conclusion', '-')} ({r['head_branch']})")
    return "\n".join(lines)


async def ci_trigger_pipeline(project_id: str, ref: str = "main", variables: str = "", provider: str = "gitlab") -> str:
    """Trigger a CI pipeline run (GitLab CI)."""
    if provider != "gitlab":
        return f"Trigger not supported for provider: {provider}"
    token = os.environ.get("GITLAB_TOKEN", "")
    base_url = os.environ.get("GITLAB_URL", "https://gitlab.com")
    if not token:
        return "[error] GITLAB_TOKEN env var required"
    payload: dict[str, Any] = {"ref": ref}
    if variables:
        try:
            payload["variables"] = json.loads(variables)
        except json.JSONDecodeError as e:
            return f"[error] Invalid variables JSON: {e}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/api/v4/projects/{project_id.replace('/', '%2F')}/pipeline",
                headers={"PRIVATE-TOKEN": token},
                json=payload,
            )
            if resp.status_code >= 400:
                return f"[error] GitLab API {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            return (
                f"Pipeline #{data['id']} triggered for {ref}\n"
                f"  Status: {data['status']}\n"
                f"  Web URL: {data.get('web_url', '')}"
            )
    except Exception as e:
        return f"[error] Failed to trigger pipeline: {e}"


async def ci_jenkins_job(job_name: str, parameters: str = "", wait: bool = False) -> str:
    """Trigger a Jenkins job/build."""
    url = os.environ.get("JENKINS_URL", "")
    user = os.environ.get("JENKINS_USER", "")
    token = os.environ.get("JENKINS_TOKEN", "")
    if not url or not user or not token:
        return "[error] JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN env vars required"
    auth_b64 = base64.b64encode(f"{user}:{token}".encode()).decode()
    build_url = f"{url.rstrip('/')}/job/{job_name}/buildWithParameters" if parameters else f"{url.rstrip('/')}/job/{job_name}/build"
    params = {}
    if parameters:
        try:
            params = json.loads(parameters)
        except json.JSONDecodeError as e:
            return f"[error] Invalid parameters JSON: {e}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if params:
                resp = await client.post(build_url, headers={"Authorization": f"Basic {auth_b64}"}, params=params)
            else:
                resp = await client.post(build_url, headers={"Authorization": f"Basic {auth_b64}"})
            if resp.status_code >= 400:
                return f"[error] Jenkins API {resp.status_code}: {resp.text[:200]}"
            location = resp.headers.get("Location", "")
            queue_item = ""
            if location:
                queue_item = f"\n  Queue item: {location}"
            if wait and location:
                queue_url = location if location.startswith("http") else f"{url.rstrip('/')}{location}"
                for _ in range(30):
                    await asyncio.sleep(2)
                    qr = await client.get(queue_url, headers={"Authorization": f"Basic {auth_b64}"})
                    if qr.status_code != 200:
                        break
                    qdata = qr.json()
                    if qdata.get("executable"):
                        build_num = qdata["executable"]["number"]
                        build_url_full = qdata["executable"]["url"]
                        return (
                            f"Jenkins job '{job_name}' build #{build_num} started\n"
                            f"  URL: {build_url_full}"
                        )
                return f"Jenkins job '{job_name}' triggered (build queued, timed out waiting)"
            return f"Jenkins job '{job_name}' triggered{queue_item}"
    except Exception as e:
        return f"[error] Failed to trigger Jenkins job: {e}"


async def ci_jenkins_status(job_name: str, build_number: int = 0) -> str:
    """Get the status of a Jenkins job/build."""
    url = os.environ.get("JENKINS_URL", "")
    user = os.environ.get("JENKINS_USER", "")
    token = os.environ.get("JENKINS_TOKEN", "")
    if not url or not user or not token:
        return "[error] JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN env vars required"
    auth_b64 = base64.b64encode(f"{user}:{token}".encode()).decode()
    try:
        status_url = f"{url.rstrip('/')}/job/{job_name}/lastBuild/api/json"
        if build_number > 0:
            status_url = f"{url.rstrip('/')}/job/{job_name}/{build_number}/api/json"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(status_url, headers={"Authorization": f"Basic {auth_b64}"})
            if resp.status_code >= 400:
                return f"[error] Jenkins API {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            return (
                f"Jenkins Job: {job_name}\n"
                f"  Build: #{data['number']}\n"
                f"  Result: {data.get('result', 'building')}\n"
                f"  Duration: {data.get('duration', 0)}ms\n"
                f"  URL: {data.get('url', '')}"
            )
    except Exception as e:
        return f"[error] Failed to get Jenkins status: {e}"


def register_ci_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(name="ci_list_workflows", description="List CI/CD workflows or pipelines (GitHub Actions or GitLab CI)", parameters={"owner": {"type": "string", "description": "Repository owner/namespace", "required": False}, "repo": {"type": "string", "description": "Repository name or project ID", "required": False}, "provider": {"type": "string", "description": "Provider: github or gitlab", "required": False}}, handler=ci_list_workflows, category="automation", timeout=30))
    registry.register(ToolSpec(name="ci_run_workflow", description="Trigger a CI/CD workflow run (GitHub Actions workflow_dispatch)", parameters={"workflow_id": {"type": "string", "description": "Workflow file name or ID", "required": True}, "owner": {"type": "string", "description": "Repository owner", "required": False}, "repo": {"type": "string", "description": "Repository name", "required": False}, "ref": {"type": "string", "description": "Branch/tag to run on", "required": False}, "inputs": {"type": "string", "description": "JSON string of workflow inputs", "required": False}, "provider": {"type": "string", "description": "Provider: github", "required": False}}, handler=ci_run_workflow, category="automation", timeout=30))
    registry.register(ToolSpec(name="ci_pipeline_status", description="Get status of a pipeline/run (GitHub Actions or GitLab CI)", parameters={"pipeline_id": {"type": "string", "description": "Run ID or pipeline ID", "required": True}, "owner": {"type": "string", "description": "Repository owner", "required": False}, "repo": {"type": "string", "description": "Repository name or project ID", "required": False}, "provider": {"type": "string", "description": "Provider: github or gitlab", "required": False}}, handler=ci_pipeline_status, category="automation", timeout=30))
    registry.register(ToolSpec(name="ci_list_runs", description="List recent workflow runs (GitHub Actions only)", parameters={"owner": {"type": "string", "description": "Repository owner", "required": False}, "repo": {"type": "string", "description": "Repository name", "required": False}, "branch": {"type": "string", "description": "Filter by branch", "required": False}, "status": {"type": "string", "description": "Filter by status (completed, queued, in_progress)", "required": False}, "provider": {"type": "string", "description": "Provider: github", "required": False}}, handler=ci_list_runs, category="automation", timeout=30))
    registry.register(ToolSpec(name="ci_trigger_pipeline", description="Trigger a GitLab CI pipeline", parameters={"project_id": {"type": "string", "description": "GitLab project ID or URL-encoded path", "required": True}, "ref": {"type": "string", "description": "Branch/tag to run on (default main)", "required": False}, "variables": {"type": "string", "description": "JSON object of pipeline variables", "required": False}, "provider": {"type": "string", "description": "Provider: gitlab", "required": False}}, handler=ci_trigger_pipeline, category="automation", timeout=30))
    registry.register(ToolSpec(name="ci_jenkins_job", description="Trigger a Jenkins job/build", parameters={"job_name": {"type": "string", "description": "Jenkins job name", "required": True}, "parameters": {"type": "string", "description": "JSON object of build parameters", "required": False}, "wait": {"type": "boolean", "description": "Wait for build to start (default false)", "required": False}}, handler=ci_jenkins_job, category="automation", timeout=120))
    registry.register(ToolSpec(name="ci_jenkins_status", description="Get status of a Jenkins job/build", parameters={"job_name": {"type": "string", "description": "Jenkins job name", "required": True}, "build_number": {"type": "integer", "description": "Build number (0 for last build)", "required": False}}, handler=ci_jenkins_status, category="automation", timeout=15))
