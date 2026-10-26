from __future__ import annotations

from typing import Any

from loguru import logger

# The one place that turns a message list into prompt text. Training and serving must agree
# byte-for-byte: an adapter trained on markup the serving path never produces learns a format that
# is then absent from every real request, and the loss looks fine while the model is useless.

# names of the tokens that close a turn, spelled in parts so this file never contains the markup
_TURN_TERMINATORS = ("im_end", "endoftext")


def render_chat(
    messages: list[dict[str, Any]], tokenizer: Any, *, add_generation_prompt: bool = True
) -> str:
    """Render with the tokenizer's own chat template, or the same fallback on both sides."""
    if tokenizer is not None and getattr(tokenizer, "chat_template", None):
        return str(
            tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=add_generation_prompt
            )
        )
    lines = [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages]
    tail = "\nassistant:" if add_generation_prompt else "\n"
    return "\n".join(lines) + tail


def stop_token_ids(tokenizer: Any) -> list[int]:
    """Every id that can end a turn, not only the tokenizer's own eos.

    A base model advertises a single ``eos_token_id``, while a chat-formatted completion closes its
    turn with the template's own terminator. Generating with only the former runs to
    ``max_new_tokens`` on every request the model actually finished.
    """
    if tokenizer is None:
        return []
    ids: list[int] = []
    declared = getattr(tokenizer, "eos_token_id", None)
    for value in declared if isinstance(declared, list | tuple) else [declared]:
        if isinstance(value, int) and value >= 0:
            ids.append(value)
    convert = getattr(tokenizer, "convert_tokens_to_ids", None)
    reverse = getattr(tokenizer, "convert_ids_to_tokens", None)
    if not (callable(convert) and callable(reverse)):
        return ids
    for name in _TURN_TERMINATORS:
        token = "<|" + name + "|>"
        try:
            value = convert(token)
        except Exception as exc:
            logger.debug("tokenizer has no id for the {} terminator: {}", name, exc)
            continue
        # a tokenizer without the token answers with its unk id instead of failing, and stopping on
        # unk would cut off every answer the moment the model hesitates
        if isinstance(value, int) and value >= 0 and value not in ids and reverse(value) == token:
            ids.append(value)
    return ids
