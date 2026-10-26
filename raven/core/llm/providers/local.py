from __future__ import annotations

import asyncio
import importlib.util
import threading
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from raven.core.config import settings
from raven.core.llm.chat_render import render_chat, stop_token_ids
from raven.core.llm.protocol import LLMProvider, LLMResponse

# find_spec only looks the packages up; importing torch here would put ~10 s and ~400 MiB on
# every process that touches the LLM layer (the factory imports this module), used or not
_ML_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("torch", "transformers", "peft"))


class LocalAdapterProvider(LLMProvider):
    """Serve a LoRA adapter produced by raven.unique.fine_tuning in this process.

    torch/transformers/peft are imported on the first completion, not at import time: the gateway
    has to start fast on a machine with or without the optional ml extra, and asking this provider
    for a completion without it is an error at first use.
    """

    def __init__(self, **overrides: Any) -> None:
        self.adapter_path = str(overrides.get("adapter_path") or settings.llm_local_adapter_path or "")
        self.max_new_tokens = int(overrides.get("max_new_tokens", settings.llm_local_max_new_tokens))
        self.temperature = float(overrides.get("temperature", 0.7))
        self.top_p = float(overrides.get("top_p", 0.9))
        self.device_map = str(overrides.get("device_map", "auto"))
        self._base_model = str(overrides.get("base_model") or settings.llm_local_base_model or "")
        self._model: Any = None
        self._tokenizer: Any = None
        self._loaded_base = ""
        self._load_lock = asyncio.Lock()

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        self._reject_tools(tools)
        await self._ensure_loaded(self._resolve_base(model))
        from transformers import TextIteratorStreamer

        inputs = await asyncio.to_thread(self._encode_sync, messages)
        streamer = TextIteratorStreamer(self._tokenizer, skip_prompt=True, skip_special_tokens=True)
        kwargs = {**inputs, "max_new_tokens": self.max_new_tokens, "streamer": streamer, **self._sampling()}
        worker = threading.Thread(target=self._generate_into, args=(kwargs,), daemon=True)
        worker.start()
        iterator = iter(streamer)
        missing = object()
        try:
            while True:
                raw = await asyncio.to_thread(next, iterator, missing)
                if raw is missing:
                    break
                if isinstance(raw, str) and raw:
                    yield raw
        finally:
            # a consumer that walks away must release the reader, or the next token read blocks
            # forever on a generation nobody is watching
            streamer.end()

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        self._reject_tools(tools)
        await self._ensure_loaded(self._resolve_base(model))
        inputs = await asyncio.to_thread(self._encode_sync, messages)
        prompt_tokens = int(inputs["input_ids"].shape[-1])
        kwargs = {**inputs, "max_new_tokens": self.max_new_tokens, **self._sampling()}
        generated = await asyncio.to_thread(self._generate_sync, kwargs)
        completion = generated[:, prompt_tokens:]
        text = str(self._tokenizer.decode(completion[0], skip_special_tokens=True))
        completion_tokens = int(completion.shape[-1])
        return LLMResponse(
            content=text,
            finish_reason="stop",
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    async def cleanup(self) -> None:
        async with self._load_lock:
            had_model = self._model is not None
            self._model = None
            self._tokenizer = None
            self._loaded_base = ""
        if had_model:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        logger.debug("Local adapter provider unloaded")

    # --- internals ---

    def _resolve_base(self, model: str) -> str:
        return model or self._base_model

    @staticmethod
    def _reject_tools(tools: list[dict[str, Any]] | None) -> None:
        if tools:
            msg = (
                "provider 'local' serves a raw causal-LM adapter and cannot emit tool calls; "
                "route tool-using agents to a provider that supports them"
            )
            raise RuntimeError(msg)

    def _sampling(self) -> dict[str, Any]:
        # the turn terminator comes from the template, and a base model's single eos is not it
        kwargs: dict[str, Any] = {"eos_token_id": stop_token_ids(self._tokenizer)}
        if self.temperature > 0:
            kwargs.update(do_sample=True, temperature=self.temperature, top_p=self.top_p)
        else:
            kwargs["do_sample"] = False
        return kwargs

    async def _ensure_loaded(self, base_model: str) -> None:
        if not _ML_AVAILABLE:
            msg = "provider 'local' needs the optional ml extra: pip install 'raven-agent[ml]'"
            raise RuntimeError(msg)
        if not base_model:
            msg = "provider 'local' needs a base model (LLM_LOCAL_BASE_MODEL or providers_config)"
            raise RuntimeError(msg)
        if not self.adapter_path:
            msg = "provider 'local' needs an adapter directory (LLM_LOCAL_ADAPTER_PATH or providers_config)"
            raise RuntimeError(msg)
        async with self._load_lock:
            if self._model is not None and self._loaded_base == base_model:
                return
            await asyncio.to_thread(self._load_sync, base_model)

    def _load_sync(self, base_model: str) -> None:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info("Loading local adapter {} over {}", self.adapter_path, base_model)
        tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        base = AutoModelForCausalLM.from_pretrained(
            base_model,
            dtype=torch.bfloat16,
            device_map=self.device_map,
            trust_remote_code=True,
        )
        model = PeftModel.from_pretrained(base, self.adapter_path)
        model.eval()
        self._tokenizer = tokenizer
        self._model = model
        self._loaded_base = base_model

    def _encode_sync(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        tokenizer = self._tokenizer
        text = self._render(messages)
        # add_special_tokens stays off: render_chat already emitted whatever the template emits, and
        # a tokenizer that adds a BOS of its own would put the request one token out of distribution
        # from every row the adapter trained on (measured on a Llama tokenizer: [1, 1, ...] vs [1, ...])
        encoded = tokenizer(text, return_tensors="pt", truncation=True, add_special_tokens=False)
        return {key: value.to(self._model.device) for key, value in encoded.items()}

    def _render(self, messages: list[dict[str, Any]]) -> str:
        # the same function the trainer used to build its rows, so a prompt at inference time is
        # rendered exactly as it was rendered during training
        return render_chat(messages, self._tokenizer)

    def _generate_sync(self, kwargs: dict[str, Any]) -> Any:
        import torch

        with torch.no_grad():
            return self._model.generate(**kwargs)

    def _generate_into(self, kwargs: dict[str, Any]) -> None:
        import torch

        try:
            with torch.no_grad():
                self._model.generate(**kwargs)
        except Exception as e:
            streamer = kwargs.get("streamer")
            if streamer is not None:
                streamer.end()
            logger.error("Local adapter generation failed: {}", e)
