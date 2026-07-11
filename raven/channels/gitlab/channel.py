from __future__ import annotations

from typing import Any

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class GitlabChannel(EnterpriseChannel):
    channel_id = "gitlab"

    async def _start(self):
        self._webhook_secret = settings.gitlab_webhook_secret or ""
        self._token = settings.gitlab_token or ""
        self._gitlab_url = settings.gitlab_url.rstrip("/") or "https://gitlab.com"

    async def _stop(self):
        self._client = None
        logger.info("[gitlab] channel stopped")

    async def handle_webhook(self, body: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        if not self._handler or not self._ready:
            return False

        event_type = (headers or {}).get("x-gitlab-event", "")
        object_kind = body.get("object_kind", "")

        parts = object_kind.split("__") if "__" in object_kind else [object_kind]
        kind = parts[0]

        project = body.get("project", {}) or {}
        project_id = str(project.get("id", ""))
        project_path = project.get("path_with_namespace", "") or project.get("path", "")

        if event_type == "Push Hook":
            user_id = body.get("user_id", "") or body.get("user_username", "")
            text = body.get("message", "") or body.get("commits", [{}])[0].get("message", "")
            ref = body.get("ref", "").replace("refs/heads/", "")
            if not text and body.get("commits"):
                text = f"{len(body['commits'])} commits pushed to {ref}"
            if not text:
                text = f"Pushed to {ref}"
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="gitlab",
                    user_id=str(user_id) or f"git:{project_path}",
                    session_id=f"gitlab:{project_id}:{user_id}",
                    text=text,
                    metadata={
                        "event_type": event_type,
                        "project_id": project_id,
                        "project_path": project_path,
                        "ref": ref,
                        "commit_count": len(body.get("commits", [])),
                    },
                )
            )
            return True

        if kind == "issue":
            obj = body.get("object_attributes", {}) or {}
            user = body.get("user", {}) or {}
            user_id = str(user.get("id", "")) or str(obj.get("author_id", ""))
            title = obj.get("title", "")
            description = obj.get("description", "")
            action = obj.get("action", "")
            text = f"Issue {action}: {title}\n{description}" if description else f"Issue {action}: {title}"
            if not title:
                return False
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="gitlab",
                    user_id=str(user_id) or f"gitlab:{project_path}",
                    session_id=f"gitlab:{project_id}:{user_id}",
                    text=text,
                    metadata={
                        "event_type": event_type,
                        "object_kind": object_kind,
                        "project_id": project_id,
                        "project_path": project_path,
                        "issue_id": obj.get("iid", ""),
                        "action": action,
                    },
                )
            )
            return True

        if kind in ("merge_request", "merge_request_note"):
            obj = body.get("object_attributes", {}) or {}
            user = body.get("user", {}) or {}
            user_id = str(user.get("id", "")) or str(obj.get("author_id", ""))
            title = obj.get("title", "")
            description = obj.get("description", "")
            action = obj.get("action", "") or obj.get("state", "")
            source_branch = obj.get("source_branch", "")
            text = f"MR {action}: {title}\n{description}" if description else f"MR {action}: {title} (branch: {source_branch})"
            if not title:
                return False
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="gitlab",
                    user_id=str(user_id) or f"gitlab:{project_path}",
                    session_id=f"gitlab:{project_id}:{user_id}",
                    text=text,
                    metadata={
                        "event_type": event_type,
                        "object_kind": object_kind,
                        "project_id": project_id,
                        "project_path": project_path,
                        "mr_iid": obj.get("iid", ""),
                        "action": action,
                        "source_branch": source_branch,
                    },
                )
            )
            return True

        if kind == "note":
            obj = body.get("object_attributes", {}) or {}
            user = body.get("user", {}) or {}
            user_id = str(user.get("id", "")) or str(obj.get("author_id", ""))
            note = obj.get("note", "")
            noteable_type = obj.get("noteable_type", "")
            if not note:
                return False
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="gitlab",
                    user_id=str(user_id) or f"gitlab:{project_path}",
                    session_id=f"gitlab:{project_id}:{user_id}",
                    text=note,
                    metadata={
                        "event_type": event_type,
                        "object_kind": object_kind,
                        "project_id": project_id,
                        "project_path": project_path,
                        "noteable_type": noteable_type,
                    },
                )
            )
            return True

        if kind in ("pipeline", "build"):
            obj = body.get("object_attributes", {}) or {}
            user = body.get("user", {}) or {}
            user_id = str(user.get("id", "")) or ""
            status = obj.get("status", "") or obj.get("detailed_status", "")
            ref = obj.get("ref", "")
            text = f"Pipeline {status} for {ref}"
            self._stats["received"] += 1
            await self._handler(
                IncomingMessage(
                    channel="gitlab",
                    user_id=str(user_id) or f"gitlab:{project_path}",
                    session_id=f"gitlab:{project_id}:{user_id}",
                    text=text,
                    metadata={
                        "event_type": event_type,
                        "object_kind": object_kind,
                        "project_id": project_id,
                        "project_path": project_path,
                        "pipeline_status": status,
                        "ref": ref,
                    },
                )
            )
            return True

        return False

    async def _send_message(self, session_id: str, message: Message):
        parts = session_id.split(":")
        project_id = parts[1] if len(parts) >= 2 else None
        if not project_id or not self._token:
            return
        import httpx
        async with httpx.AsyncClient(base_url=f"{self._gitlab_url}/api/v4", timeout=15) as client:
            resp = await client.post(
                f"/projects/{project_id}/issues",
                json={"title": message.content[:4000]},
                headers={"PRIVATE-TOKEN": self._token},
            )
            resp.raise_for_status()
