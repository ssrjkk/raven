from __future__ import annotations

from email.message import Message


def plain_body(parsed: Message) -> str:
    """Decode the text/plain body, picking the first plain part out of a multipart message."""
    payload: object = None
    if parsed.is_multipart():
        for part in parsed.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                break
    else:
        payload = parsed.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return payload if isinstance(payload, str) else ""
