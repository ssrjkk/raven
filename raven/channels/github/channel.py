from __future__ import annotations

from typing import Any

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class GithubChannel(EnterpriseChannel):
    channel_id = "github"

    async def _start(self):
        self._token = settings.github_token or ""
        logger.info("[github] channel started")

    async def _stop(self):
        logger.info("[github] channel stopped")

    async def handle_webhook(self, body: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        if not self._handler or not self._ready:
            return False

        gh_event = (headers or {}).get("x-github-event", "")
        repo_full = ((body.get("repository") or {}).get("full_name", ""))
        sender = ((body.get("sender") or {}).get("login", ""))

        if gh_event == "push":
            ref = body.get("ref", "").replace("refs/heads/", "")
            commits = body.get("commits", [])
            msg = commits[0].get("message", "") if commits else f"Pushed to {ref}"
            user_id = body.get("pusher", {}).get("name", "") or sender
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="github",
                    user_id=str(user_id) or f"github:{repo_full}",
                    session_id=f"github:{repo_full}:push:{ref}",
                    text=msg,
                    metadata={"event": gh_event, "repo": repo_full, "ref": ref, "commit_count": len(commits)},
                )
            )
            return True

        if gh_event == "pull_request":
            pr = body.get("pull_request") or {}
            action = body.get("action", "")
            title = pr.get("title", "")
            body_text = pr.get("body", "") or ""
            number = pr.get("number", "")
            user_id = pr.get("user", {}).get("login", "") or sender
            ref = pr.get("head", {}).get("ref", "")
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="github",
                    user_id=str(user_id) or f"github:{repo_full}",
                    session_id=f"github:{repo_full}:pr:{number}",
                    text=f"PR {action}: {title}\n{body_text}" if body_text else f"PR {action}: {title}",
                    metadata={"event": gh_event, "repo": repo_full, "pr_number": number, "action": action, "ref": ref},
                )
            )
            return True

        if gh_event == "issues":
            issue = body.get("issue") or {}
            action = body.get("action", "")
            title = issue.get("title", "")
            body_text = issue.get("body", "") or ""
            number = issue.get("number", "")
            user_id = issue.get("user", {}).get("login", "") or sender
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="github",
                    user_id=str(user_id) or f"github:{repo_full}",
                    session_id=f"github:{repo_full}:issue:{number}",
                    text=f"Issue {action}: {title}\n{body_text}" if body_text else f"Issue {action}: {title}",
                    metadata={"event": gh_event, "repo": repo_full, "issue_number": number, "action": action},
                )
            )
            return True

        if gh_event in ("issue_comment", "pull_request_review_comment"):
            issue = body.get("issue") or body.get("pull_request") or {}
            comment = body.get("comment") or {}
            user_id = comment.get("user", {}).get("login", "") or sender
            body_text = comment.get("body", "")
            number = issue.get("number", "")
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="github",
                    user_id=str(user_id) or f"github:{repo_full}",
                    session_id=f"github:{repo_full}:comment:{number}",
                    text=body_text or f"Comment on #{number}",
                    metadata={"event": gh_event, "repo": repo_full, "issue_number": number},
                )
            )
            return True

        if gh_event == "pull_request_review":
            pr = body.get("pull_request") or {}
            review = body.get("review") or {}
            user_id = review.get("user", {}).get("login", "") or sender
            state = review.get("state", "")
            body_text = review.get("body", "")
            number = pr.get("number", "")
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="github",
                    user_id=str(user_id) or f"github:{repo_full}",
                    session_id=f"github:{repo_full}:review:{number}",
                    text=f"Review {state}: {body_text}" if body_text else f"Review {state} on PR #{number}",
                    metadata={"event": gh_event, "repo": repo_full, "pr_number": number, "review_state": state},
                )
            )
            return True

        if gh_event == "workflow_run":
            run = body.get("workflow_run") or {}
            action = body.get("action", "")
            workflow_name = run.get("name", "")
            status = run.get("status", "")
            conclusion = run.get("conclusion", "")
            user_id = (run.get("actor") or {}).get("login", "") or sender
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="github",
                    user_id=str(user_id) or f"github:{repo_full}",
                    session_id=f"github:{repo_full}:workflow:{workflow_name}",
                    text=f"Workflow {action}: {workflow_name} ({conclusion or status})",
                    metadata={"event": gh_event, "repo": repo_full, "workflow": workflow_name, "status": status, "conclusion": conclusion},
                )
            )
            return True

        logger.debug("[github] unhandled event: {}", gh_event)
        return False

    async def _send_message(self, session_id: str, message: Message):
        parts = session_id.split(":")
        if len(parts) < 3:
            return
        target_type = parts[2]
        target_id = parts[3] if len(parts) >= 4 else ""
        if target_type == "issue" and target_id and self._token:
            import httpx
            repo = parts[1]
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"https://api.github.com/repos/{repo}/issues/{target_id}/comments",
                    json={"body": message.content[:4000]},
                    headers={"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github.v3+json", "User-Agent": "raven-ai/1.0"},
                )
                resp.raise_for_status()
