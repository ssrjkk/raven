from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.llm.chat_render import render_chat
from raven.core.security.context_filter import redact_pii

try:
    import torch

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    torch = None

try:
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        PreTrainedModel,
        PreTrainedTokenizerBase,
        TrainingArguments,
    )

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _TRANSFORMERS_AVAILABLE = False
    AutoModelForCausalLM = None
    AutoTokenizer = None
    TrainingArguments = None
    PreTrainedModel = None
    PreTrainedTokenizerBase = None

try:
    from peft import LoraConfig, PeftModel, TaskType, get_peft_model

    _PEFT_AVAILABLE = True
except ImportError:
    _PEFT_AVAILABLE = False
    LoraConfig = None
    get_peft_model = None
    PeftModel = None
    TaskType = None

try:
    from datasets import Dataset, load_dataset

    _DATASETS_AVAILABLE = True
except ImportError:
    _DATASETS_AVAILABLE = False
    Dataset = None
    load_dataset = None

try:
    import wandb

    _WANDB_AVAILABLE = True
except ImportError:
    _WANDB_AVAILABLE = False
    wandb = None


SUPPORTED_MODEL_TYPES: dict[str, str] = {
    "llama": "meta-llama/Llama-2-7b-hf",
    "mistral": "mistralai/Mistral-7B-v0.1",
    "gpt_neox": "EleutherAI/gpt-neox-20b",
    "falcon": "tiiuae/falcon-7b",
    "phi": "microsoft/phi-2",
    "qwen": "Qwen/Qwen-7B",
}


@dataclass
class ConversationExample:
    messages: list[dict[str, str]]
    system_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    consented: bool = False
    """Whether the people in this row agreed to be trained on. Empty corpus is a better outcome than
    an unconsented one: the builder drops the row rather than quietly including it."""


@dataclass
class CodeExample:
    code: str
    language: str = ""
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    consented: bool = False


@dataclass
class DatasetConfig:
    max_length: int = 2048
    test_split: float = 0.1
    require_consent: bool = True
    redact_pii: bool = True


@dataclass
class TrainingConfig:
    output_dir: str = "ft_checkpoints"
    num_epochs: int = 3
    batch_size: int = 4
    gradient_accumulation_steps: int = 4
    learning_rate: float = 2e-4
    warmup_steps: int = 100
    logging_steps: int = 10
    save_steps: int = 500
    eval_steps: int = 500
    max_grad_norm: float = 1.0
    use_lora: bool = True
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    use_qlora: bool = False
    bnb_4bit_quant_type: str = "nf4"
    bnb_4bit_use_double_quant: bool = True
    model_type: str = "llama"
    model_name_or_path: str = ""
    load_in_8bit: bool = False
    load_in_4bit: bool = False
    deepspeed: str = ""
    fsdp: str = ""
    seed: int = 42


@dataclass
class EvalResult:
    perplexity: float = 0.0
    accuracy: float = 0.0
    response_quality: float = 0.0
    loss: float = 0.0
    num_samples: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Checkpoint:
    path: Path
    step: int
    epoch: int
    metrics: dict[str, float]
    timestamp: float = 0.0


class DatasetBuilder:
    def __init__(self, config: DatasetConfig | None = None) -> None:
        self._config = config or DatasetConfig()
        self._conversations: list[ConversationExample] = []
        self._code_samples: list[CodeExample] = []

    def add_conversation(self, conversation: ConversationExample) -> None:
        self._conversations.append(conversation)

    def add_conversations(self, conversations: list[ConversationExample]) -> None:
        self._conversations.extend(conversations)

    def add_code(self, code_sample: CodeExample) -> None:
        self._code_samples.append(code_sample)

    def add_code_samples(self, samples: list[CodeExample]) -> None:
        self._code_samples.extend(samples)

    def add_from_jsonl(self, path: str | Path, source_type: str = "conversation") -> int:
        path_obj = Path(path)
        if not path_obj.exists():
            msg = f"Dataset file not found: {path}"
            raise FileNotFoundError(msg)
        count = 0
        with path_obj.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if source_type == "conversation":
                    self._conversations.append(
                        ConversationExample(
                            messages=data.get("messages", []),
                            system_prompt=data.get("system_prompt", ""),
                            metadata=data.get("metadata", {}),
                        )
                    )
                elif source_type == "code":
                    self._code_samples.append(
                        CodeExample(
                            code=data.get("code", ""),
                            language=data.get("language", ""),
                            description=data.get("description", ""),
                            metadata=data.get("metadata", {}),
                        )
                    )
                count += 1
        logger.info("Loaded {} {} samples from {}", count, source_type, path)
        return count

    def _text(self, value: str) -> str:
        return redact_pii(value) if self._config.redact_pii else value

    def _consented(self, rows: list[Any]) -> list[Any]:
        if not self._config.require_consent:
            return list(rows)
        return [row for row in rows if row.consented]

    def _messages(self, conv: ConversationExample) -> list[dict[str, str]]:
        messages = [{"role": m["role"], "content": self._text(m.get("content", ""))} for m in conv.messages]
        if conv.system_prompt:
            messages.insert(0, {"role": "system", "content": self._text(conv.system_prompt)})
        return messages

    def _format_code(self, code: CodeExample) -> str:
        description = self._text(code.description)
        header = f"// {description}" if description else ""
        if code.language:
            header = f"// Language: {code.language}\n{header}"
        return f"{header}\n{self._text(code.code)}" if header else self._text(code.code)

    def build_dataset(self) -> Any:
        """Rows carry messages, not rendered text: only the tokenizer knows its own chat template."""
        if not _DATASETS_AVAILABLE:
            raise RuntimeError("`datasets` library is required to build a Dataset object")
        conversations = self._consented(self._conversations)
        code_samples = self._consented(self._code_samples)
        skipped = (len(self._conversations) - len(conversations)) + (len(self._code_samples) - len(code_samples))
        if skipped:
            logger.warning("Dataset skipped {} row(s) without consent", skipped)
        if not conversations and not code_samples:
            raise RuntimeError(
                "no consented rows to train on: add them with consented=True or set require_consent=False"
            )
        data = {
            "messages": [self._messages(c) for c in conversations] + [[] for _ in code_samples],
            "text": [""] * len(conversations) + [self._format_code(c) for c in code_samples],
        }
        dataset = Dataset.from_dict(data)
        rows = len(conversations) + len(code_samples)
        if rows < 2:
            # `datasets` rejects both a zero and a proportional split for a single row -- "the
            # resulting train set will be empty", then "test_size should be positive" -- which reads
            # as a library crash rather than as the small corpus it is
            logger.warning("Corpus has one row: no held-out split is possible, training on it whole")
            return {"train": dataset, "test": dataset.select([])}
        split = dataset.train_test_split(test_size=self._config.test_split, seed=42)
        logger.info("Built dataset: {} train, {} test samples", len(split["train"]), len(split["test"]))
        return split

    def corpus_hash(self) -> str:
        """sha256 over the rows exactly as they enter the tokenizer, redaction included. A dataset
        card without this cannot say which corpus a checkpoint came from."""
        lines = [json.dumps(self._messages(c), ensure_ascii=False, sort_keys=True) for c in self._consented(self._conversations)]
        lines += [self._format_code(c) for c in self._consented(self._code_samples)]
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

    def tokenize_dataset(self, dataset: Any, tokenizer: Any) -> Any:
        def encode(examples: dict[str, Any]) -> dict[str, Any]:
            texts = [
                render_chat(messages, tokenizer) if messages else raw
                for messages, raw in zip(examples["messages"], examples["text"], strict=True)
            ]
            return tokenizer(
                texts,
                truncation=True,
                padding="max_length",
                max_length=self._config.max_length,
                return_overflowing_tokens=False,
                # the chat template already emitted the special tokens; adding another pair would
                # train a sequence the serving path never produces
                add_special_tokens=False,
            )

        tokenized = dataset.map(encode, batched=True, remove_columns=["messages", "text"])
        logger.info("Tokenized dataset: {} samples", len(tokenized))
        return tokenized

    def stats(self) -> dict[str, Any]:
        consented_conversations = self._consented(self._conversations)
        consented_code = self._consented(self._code_samples)
        return {
            "conversations": len(self._conversations),
            "code_samples": len(self._code_samples),
            "consented": {"conversations": len(consented_conversations), "code_samples": len(consented_code)},
            "excluded_without_consent": (len(self._conversations) - len(consented_conversations))
            + (len(self._code_samples) - len(consented_code)),
            "policy": {"require_consent": self._config.require_consent, "redact_pii": self._config.redact_pii},
            "config": {
                "max_length": self._config.max_length,
                "test_split": self._config.test_split,
            },
        }

    def dataset_card(self) -> dict[str, Any]:
        """What the corpus actually is, derived from the rows rather than asserted by whoever added
        them: counts by role, size, the consent and redaction policies in force, and the hash the
        checkpoint's card has to match."""
        rows = self._consented(self._conversations)
        codes = self._consented(self._code_samples)
        roles: dict[str, int] = {}
        for conv in rows:
            for message in self._messages(conv):
                roles[message["role"]] = roles.get(message["role"], 0) + 1
        characters = sum(len(message["content"]) for conv in rows for message in self._messages(conv))
        characters += sum(len(self._format_code(code)) for code in codes)
        return {
            "rows": {"conversations": len(rows), "code_samples": len(codes)},
            "messages_by_role": dict(sorted(roles.items())),
            "characters": characters,
            "policy": self.stats()["policy"],
            "excluded_without_consent": self.stats()["excluded_without_consent"],
            "corpus_sha256": self.corpus_hash(),
        }

    def write_card(self, path: str | Path) -> Path:
        """The card travels with the adapter: a checkpoint directory nobody can tie to a corpus is
        not a reproducible artifact."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.dataset_card(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return target

    def clear(self) -> None:
        self._conversations.clear()
        self._code_samples.clear()


#: RAVEN_TRAIN_TRACKING is the switch. Importable is not consent: a self-hosted install that happens
#: to have `wandb` in its environment must not publish metrics, and `log_checkpoint` uploads model
#: weights, because the package resolved.
_TRACKING_ENV_VAR = "RAVEN_TRAIN_TRACKING"
_TRACKING_ON = frozenset({"1", "true", "yes", "on"})


def training_tracking_enabled() -> bool:
    return os.environ.get(_TRACKING_ENV_VAR, "").strip().lower() in _TRACKING_ON


class TrainingMonitor:
    def __init__(self, use_wandb: bool = False, client: Any = None) -> None:
        # the client is held, not reached for as a module global: that global is only bound when
        # the optional extra is installed, which made every test of this class a reload or a patch
        self._client = client if client is not None else (wandb if use_wandb and _WANDB_AVAILABLE else None)
        self._use_wandb = self._client is not None
        self._run: Any = None
        self._metrics_log: list[dict[str, Any]] = []

    def log_metrics(self, metrics: dict[str, float]) -> None:
        if self._use_wandb and self._run:
            self._client.log(metrics)
        self._metrics_log.append(metrics)
        for key, value in metrics.items():
            logger.info("Training metric - {}: {}", key, value)

    def log_checkpoint(self, checkpoint: Checkpoint, metrics: dict[str, float] | None = None) -> None:
        if self._use_wandb and self._run:
            artifact = self._client.Artifact(f"checkpoint-{checkpoint.step}", type="model")
            artifact.add_dir(str(checkpoint.path))
            self._run.log_artifact(artifact)
        logger.info("Checkpoint logged: step={}, path={}", checkpoint.step, checkpoint.path)

    def finish(self) -> None:
        if self._use_wandb and self._run:
            self._client.finish()
        logger.info("Training monitor finished, logged {} metric entries", len(self._metrics_log))


class FineTuningPipeline:
    def __init__(self, config: TrainingConfig | None = None) -> None:
        self._config = config or TrainingConfig()
        self._model: Any = None
        self._tokenizer: Any = None
        self._checkpoints: list[Checkpoint] = []
        self._best_metric: float = float("inf")
        self._best_checkpoint: Checkpoint | None = None

    @property
    def config(self) -> TrainingConfig:
        return self._config

    @property
    def model(self) -> Any:
        return self._model

    @property
    def tokenizer(self) -> Any:
        return self._tokenizer

    def _resolve_model_name(self) -> str:
        if self._config.model_name_or_path:
            return self._config.model_name_or_path
        model_id = SUPPORTED_MODEL_TYPES.get(self._config.model_type)
        if model_id:
            return model_id
        msg = f"Unknown model type '{self._config.model_type}'. Supported: {list(SUPPORTED_MODEL_TYPES)}"
        raise ValueError(msg)

    def _validate_dependencies(self) -> None:
        missing: list[str] = []
        if not _TORCH_AVAILABLE:
            missing.append("torch")
        if not _TRANSFORMERS_AVAILABLE:
            missing.append("transformers")
        if self._config.use_lora and not _PEFT_AVAILABLE:
            missing.append("peft")
        if missing:
            msg = f"Missing required dependencies: {', '.join(missing)}. Install with: pip install {' '.join(missing)}"
            raise RuntimeError(msg)

    def load_model(self, model_name: str | None = None) -> None:
        self._validate_dependencies()
        model_id = model_name or self._resolve_model_name()
        logger.info("Loading model: {}", model_id)
        quantization_kwargs: dict[str, Any] = {}
        if self._config.use_qlora and _TORCH_AVAILABLE:
            try:
                from transformers import BitsAndBytesConfig

                quantization_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type=self._config.bnb_4bit_quant_type,
                    bnb_4bit_use_double_quant=self._config.bnb_4bit_use_double_quant,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                )
            except ImportError:
                logger.warning("bitsandbytes not available for QLoRA, falling back to standard loading")
        elif self._config.load_in_4bit:
            quantization_kwargs["load_in_4bit"] = True
        elif self._config.load_in_8bit:
            quantization_kwargs["load_in_8bit"] = True

        self._tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        self._model = AutoModelForCausalLM.from_pretrained(
            model_id,
            dtype=torch.bfloat16 if _TORCH_AVAILABLE else None,
            device_map="auto",
            trust_remote_code=True,
            **quantization_kwargs,
        )
        self._model.config.use_cache = False

        if self._config.use_lora and _PEFT_AVAILABLE:
            self._apply_lora()

        param_count = sum(p.numel() for p in self._model.parameters())
        trainable_count = sum(p.numel() for p in self._model.parameters() if p.requires_grad)
        logger.info("Model loaded: {} total params, {} trainable", param_count, trainable_count)

    def _apply_lora(self) -> None:
        if not _PEFT_AVAILABLE or LoraConfig is None or get_peft_model is None:
            return
        target_modules: list[str] = []
        if self._config.model_type in ("llama", "mistral", "qwen"):
            target_modules = ["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
        elif self._config.model_type in ("gpt_neox", "falcon"):
            target_modules = ["query_key_value", "dense", "dense_h_to_4h", "dense_4h_to_h"]
        else:
            target_modules = ["q_proj", "v_proj"]

        lora_config = LoraConfig(
            r=self._config.lora_r,
            lora_alpha=self._config.lora_alpha,
            target_modules=target_modules,
            lora_dropout=self._config.lora_dropout,
            bias="none",
            task_type=TaskType.CAUSAL_LM,
        )
        self._model = get_peft_model(self._model, lora_config)
        logger.info(
            "LoRA applied: rank={}, alpha={}, targets={}", self._config.lora_r, self._config.lora_alpha, target_modules
        )

    def _compute_perplexity(self, eval_loss: float) -> float:
        if eval_loss < 0:
            return float("inf")
        return float(math.exp(eval_loss))

    def evaluate(self, eval_dataset: Any) -> EvalResult:
        if not _TRANSFORMERS_AVAILABLE or not _TORCH_AVAILABLE:
            raise RuntimeError("transformers and torch are required for evaluation")
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("Model must be loaded before evaluation")

        logger.info("Starting evaluation...")
        self._model.eval()
        total_loss = 0.0
        total_tokens = 0
        correct = 0
        total = 0

        from torch.utils.data import DataLoader

        # a datasets.Dataset hands DataLoader python lists unless it is told to emit tensors
        eval_dataset.set_format(type="torch", columns=["input_ids", "attention_mask"])
        eval_loader = DataLoader(eval_dataset, batch_size=self._config.batch_size)

        with torch.no_grad():
            for batch in eval_loader:
                input_ids = batch["input_ids"].to(self._model.device)
                attention_mask = batch["attention_mask"].to(self._model.device)
                # pad tokens carry no signal: the model averages its loss over the non-ignored
                # positions, so weighting must use the same count, on the shifted labels
                labels = input_ids.clone()
                labels[attention_mask == 0] = -100
                token_mask = labels[:, 1:] != -100
                scored = int(token_mask.sum().item())
                if scored == 0:
                    continue

                outputs = self._model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
                total_loss += outputs.loss.item() * scored
                total_tokens += scored

                predictions = outputs.logits.argmax(dim=-1)
                correct += int(((predictions[:, :-1] == labels[:, 1:]) & token_mask).sum().item())
                total += scored

        avg_loss = total_loss / total_tokens if total_tokens > 0 else float("inf")
        perplexity = self._compute_perplexity(avg_loss)
        accuracy = correct / total if total > 0 else 0.0

        result = EvalResult(
            perplexity=round(perplexity, 4),
            accuracy=round(accuracy, 4),
            response_quality=round(1.0 / (1.0 + avg_loss), 4),
            loss=round(avg_loss, 4),
            num_samples=len(eval_dataset),
        )
        logger.info("Evaluation: perplexity={}, accuracy={}, loss={}", result.perplexity, result.accuracy, result.loss)
        return result

    def train(self, train_dataset: Any, eval_dataset: Any | None = None) -> dict[str, Any]:
        if not _TRANSFORMERS_AVAILABLE or not _TORCH_AVAILABLE:
            raise RuntimeError("transformers and torch are required for training")
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("Model must be loaded before training")

        logger.info("Starting training for {} epochs...", self._config.num_epochs)
        output_dir = Path(self._config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        training_args = TrainingArguments(
            output_dir=str(output_dir),
            num_train_epochs=self._config.num_epochs,
            per_device_train_batch_size=self._config.batch_size,
            per_device_eval_batch_size=self._config.batch_size,
            gradient_accumulation_steps=self._config.gradient_accumulation_steps,
            learning_rate=self._config.learning_rate,
            warmup_steps=self._config.warmup_steps,
            logging_steps=self._config.logging_steps,
            save_steps=self._config.save_steps,
            eval_steps=self._config.eval_steps,
            eval_strategy="steps" if eval_dataset is not None else "no",
            save_total_limit=3,
            load_best_model_at_end=eval_dataset is not None,
            max_grad_norm=self._config.max_grad_norm,
            report_to=["none"],
            fp16=_TORCH_AVAILABLE and torch.cuda.is_available(),
            bf16=_TORCH_AVAILABLE and torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
            dataloader_pin_memory=False,
            remove_unused_columns=False,
            seed=self._config.seed,
            ddp_find_unused_parameters=False if self._config.use_lora else None,
            deepspeed=self._config.deepspeed or None,
            fsdp=self._config.fsdp or None,
        )

        from transformers import DataCollatorForLanguageModeling, Trainer

        trainer = Trainer(
            model=self._model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            processing_class=self._tokenizer,
            # tokenize_dataset yields input_ids/attention_mask only; without labels the causal-LM
            # head returns no loss and Trainer aborts on the first step. This collator sets
            # labels=input_ids and masks the padding, which is what the loss then averages over.
            data_collator=DataCollatorForLanguageModeling(tokenizer=self._tokenizer, mlm=False),
        )

        train_result = trainer.train()
        metrics = {
            "train_loss": float(train_result.training_loss) if hasattr(train_result, "training_loss") else 0.0,
            "global_step": train_result.global_step if hasattr(train_result, "global_step") else 0,
            "epoch": train_result.epoch if hasattr(train_result, "epoch") else 0.0,
        }
        logger.info("Training completed: loss={}, steps={}", metrics["train_loss"], metrics["global_step"])

        if eval_dataset is not None:
            eval_metrics = trainer.evaluate()
            metrics["eval_loss"] = eval_metrics.get("eval_loss", 0.0)
            metrics["eval_perplexity"] = self._compute_perplexity(metrics["eval_loss"])

        final_path = output_dir / "final"
        trainer.save_model(str(final_path))
        if self._tokenizer:
            self._tokenizer.save_pretrained(str(final_path))
        logger.info("Final model saved to {}", final_path)

        checkpoint = Checkpoint(
            path=final_path,
            step=int(metrics.get("global_step", 0)),
            epoch=int(metrics.get("epoch", 0)),
            metrics=metrics,
            timestamp=time.time(),
        )
        self._checkpoints.append(checkpoint)
        if metrics.get("eval_loss", float("inf")) < self._best_metric:
            self._best_metric = metrics.get("eval_loss", float("inf"))
            self._best_checkpoint = checkpoint

        return metrics

    def save_checkpoint(
        self, path: str | Path, step: int = 0, epoch: int = 0, metrics: dict[str, float] | None = None
    ) -> Checkpoint:
        save_path = Path(path)
        save_path.mkdir(parents=True, exist_ok=True)
        if self._model is not None:
            if _TRANSFORMERS_AVAILABLE:
                self._model.save_pretrained(str(save_path), safe_serialization=True)
            if self._tokenizer is not None and _TRANSFORMERS_AVAILABLE:
                self._tokenizer.save_pretrained(str(save_path))

        meta = {"step": step, "epoch": epoch, **(metrics or {})}
        meta_path = save_path / "checkpoint_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        cp = Checkpoint(
            path=save_path,
            step=step,
            epoch=epoch,
            metrics=metrics or {},
            timestamp=time.time(),
        )
        self._checkpoints.append(cp)
        logger.info("Checkpoint saved at step {} to {}", step, save_path)
        return cp

    def load_checkpoint(self, path: str | Path) -> None:
        load_path = Path(path)
        if not load_path.exists():
            msg = f"Checkpoint not found: {load_path}"
            raise FileNotFoundError(msg)
        self._validate_dependencies()

        meta_path = load_path / "checkpoint_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            logger.info("Loading checkpoint from step {}, epoch {}", meta.get("step", 0), meta.get("epoch", 0))

        if _TRANSFORMERS_AVAILABLE and _PEFT_AVAILABLE:
            model_id = self._resolve_model_name()
            self._tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
            base_model = AutoModelForCausalLM.from_pretrained(
                model_id,
                dtype=torch.bfloat16,
                device_map="auto",
                trust_remote_code=True,
            )
            self._model = PeftModel.from_pretrained(base_model, str(load_path))
            logger.info("Checkpoint loaded from {}", load_path)
        else:
            logger.warning("Cannot fully restore model without transformers/peft")

    def list_checkpoints(self) -> list[Checkpoint]:
        return list(self._checkpoints)

    def get_best_checkpoint(self) -> Checkpoint | None:
        return self._best_checkpoint

    def get_model_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "model_type": self._config.model_type,
            "model_name": self._resolve_model_name(),
            "trainable_params": 0,
            "total_params": 0,
            "checkpoints": len(self._checkpoints),
        }
        if self._model is not None and _TORCH_AVAILABLE:
            info["trainable_params"] = sum(p.numel() for p in self._model.parameters() if p.requires_grad)
            info["total_params"] = sum(p.numel() for p in self._model.parameters())
        return info

    def unload_model(self) -> None:
        self._model = None
        self._tokenizer = None
        if _TORCH_AVAILABLE and torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Model unloaded, GPU cache cleared")

    async def train_with_wandb(
        self, config: TrainingConfig, dataset: Any, client: Any = None
    ) -> tuple[Any, dict[str, Any]]:
        """Train, optionally mirroring metrics to W&B.

        The mirror needs a decision from the operator: either an explicit `client` (the caller already
        holds one, so it wants this) or RAVEN_TRAIN_TRACKING on. Without either, this is `train()` and
        nothing leaves the machine -- the upload includes checkpoint artifacts, i.e. model weights.
        """
        self._config = config
        if client is None and not training_tracking_enabled():
            logger.info("Training tracking is off; set {}=on to mirror metrics", _TRACKING_ENV_VAR)
            self.load_model()
            metrics = self.train(dataset)
            return self._model, metrics

        wandb_client = client if client is not None else (wandb if _WANDB_AVAILABLE else None)
        if wandb_client is None:
            logger.warning("W&B not available, training without monitoring")
            self.load_model()
            metrics = self.train(dataset)
            return self._model, metrics

        loop = asyncio.get_running_loop()

        def _train_sync() -> tuple[Any, dict[str, Any]]:
            wandb_run = wandb_client.init(
                project="fine-tuning",
                config={
                    "learning_rate": config.learning_rate,
                    "num_epochs": config.num_epochs,
                    "batch_size": config.batch_size,
                    "gradient_accumulation_steps": config.gradient_accumulation_steps,
                    "model_type": config.model_type,
                    "use_lora": config.use_lora,
                    "lora_r": config.lora_r,
                    "lora_alpha": config.lora_alpha,
                },
                reinit=True,
            )
            monitor = TrainingMonitor(client=wandb_client)
            monitor._run = wandb_run
            try:
                self.load_model()
                metrics = self.train(dataset)
                train_loss = metrics.get("train_loss", 0.0)
                eval_loss = metrics.get("eval_loss", 0.0)
                perplexity = metrics.get("eval_perplexity", 0.0)
                log_metrics = {
                    "train/loss": train_loss,
                    "train/learning_rate": config.learning_rate,
                }
                if eval_loss:
                    log_metrics["eval/loss"] = eval_loss
                if perplexity:
                    log_metrics["eval/perplexity"] = perplexity
                monitor.log_metrics(log_metrics)
                for cp in self._checkpoints:
                    monitor.log_checkpoint(cp)
                return self._model, metrics
            finally:
                monitor.finish()
                wandb_run.finish()

        return await loop.run_in_executor(None, _train_sync)
