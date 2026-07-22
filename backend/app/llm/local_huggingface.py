from __future__ import annotations

import asyncio
import logging
import threading
from time import perf_counter
from typing import Any

from backend.app.core.config import SearchLLMSettings, load_search_llm_settings
from backend.app.search.exceptions import SearchModelUnavailableError

from .prompts import REPAIR_SYSTEM_PROMPT, SCHEMA_EXPECTATIONS, SEARCH_INTENT_SYSTEM_PROMPT


logger = logging.getLogger(__name__)


class LocalHuggingFaceSearchIntentClient:
    _tokenizer: Any | None = None
    _model: Any | None = None
    _device: str | None = None
    _model_key: tuple[str, str | None, str] | None = None
    _loading = False
    _load_error: str | None = None
    _load_failed_at: float | None = None
    _load_lock = threading.Lock()

    def __init__(self, settings: SearchLLMSettings | None = None):
        self.settings = settings or load_search_llm_settings()
        self._semaphore = asyncio.Semaphore(max(1, self.settings.max_concurrency))

    async def generate_search_intent(self, query: str) -> str:
        messages = [
            {"role": "system", "content": SEARCH_INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        return await self._generate(messages)

    async def repair_search_intent(self, malformed_output: str, validation_error: str) -> str:
        repair_input = (
            f"{SCHEMA_EXPECTATIONS}\n"
            f"Validation error:\n{validation_error[:2000]}\n\n"
            f"Malformed output:\n{malformed_output[:4000]}"
        )
        messages = [
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": repair_input},
        ]
        return await self._generate(messages)

    async def _generate(self, messages: list[dict[str, str]]) -> str:
        if not self.settings.enabled:
            raise SearchModelUnavailableError("local search LLM is disabled")
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._generate_sync, messages),
                    timeout=max(1, self.settings.timeout_seconds),
                )
            except asyncio.TimeoutError as exc:
                raise SearchModelUnavailableError("local search LLM timed out") from exc
            except SearchModelUnavailableError:
                raise
            except RuntimeError as exc:
                self._raise_generation_runtime_error(exc)
            except Exception as exc:
                logger.exception("local search LLM generation failed")
                raise SearchModelUnavailableError("local search LLM failed during generation") from exc

    def _generate_sync(self, messages: list[dict[str, str]]) -> str:
        tokenizer, model, device, torch = self._ensure_model_sync()
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max(1, self.settings.max_input_tokens),
        )
        inputs = {key: value.to(device) for key, value in inputs.items()}
        input_length = inputs["input_ids"].shape[-1]

        with torch.inference_mode():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max(1, self.settings.max_new_tokens),
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
        generated_ids = output_ids[0][input_length:]
        return tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

    def _ensure_model_sync(self):
        model_key = self._settings_key()
        if (
            self.__class__._tokenizer is not None
            and self.__class__._model is not None
            and self.__class__._model_key == model_key
        ):
            return self.__class__._tokenizer, self.__class__._model, self.__class__._device, self._torch()
        self._raise_cached_load_failure_if_needed(model_key)

        with self.__class__._load_lock:
            if (
                self.__class__._tokenizer is not None
                and self.__class__._model is not None
                and self.__class__._model_key == model_key
            ):
                return self.__class__._tokenizer, self.__class__._model, self.__class__._device, self._torch()
            self._raise_cached_load_failure_if_needed(model_key)

            self.__class__._loading = True
            try:
                torch = self._torch()
                AutoModelForCausalLM, AutoTokenizer = self._transformers()
                device = self._resolve_device(torch)
                torch_dtype = self._dtype_for_device(torch, device)
                load_kwargs: dict[str, Any] = {
                    "trust_remote_code": False,
                    "use_safetensors": True,
                }
                tokenizer_kwargs: dict[str, Any] = {"trust_remote_code": False}
                if self.settings.revision:
                    load_kwargs["revision"] = self.settings.revision
                    tokenizer_kwargs["revision"] = self.settings.revision
                if torch_dtype is not None:
                    load_kwargs["torch_dtype"] = torch_dtype

                tokenizer = AutoTokenizer.from_pretrained(self.settings.model_id, **tokenizer_kwargs)
                model = AutoModelForCausalLM.from_pretrained(self.settings.model_id, **load_kwargs)
                model.to(device)
                model.eval()
            except SearchModelUnavailableError as exc:
                self._record_load_failure(model_key, str(exc))
                raise
            except Exception as exc:
                self._record_load_failure(model_key, "could not load local search LLM")
                logger.exception("could not load local search LLM")
                raise SearchModelUnavailableError("could not load local search LLM") from exc
            finally:
                self.__class__._loading = False

            self.__class__._tokenizer = tokenizer
            self.__class__._model = model
            self.__class__._device = device
            self.__class__._model_key = model_key
            self.__class__._load_error = None
            self.__class__._load_failed_at = None
            return tokenizer, model, device, torch

    def _settings_key(self) -> tuple[str, str | None, str]:
        return (self.settings.model_id, self.settings.revision, self.settings.device)

    def _raise_cached_load_failure_if_needed(self, model_key: tuple[str, str | None, str]) -> None:
        if self.__class__._load_error is None or self.__class__._model_key != model_key:
            return
        failed_at = self.__class__._load_failed_at or 0
        cooldown = max(0, self.settings.load_failure_cooldown_seconds)
        if perf_counter() - failed_at < cooldown:
            raise SearchModelUnavailableError(self.__class__._load_error)

    def _record_load_failure(self, model_key: tuple[str, str | None, str], message: str) -> None:
        self.__class__._model_key = model_key
        self.__class__._load_error = message
        self.__class__._load_failed_at = perf_counter()

    def _resolve_device(self, torch) -> str:
        device = (self.settings.device or "auto").strip().lower()
        if device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise SearchModelUnavailableError("SEARCH_LLM_DEVICE=cuda but CUDA is not available")
        if device not in {"cpu", "cuda"}:
            raise SearchModelUnavailableError("SEARCH_LLM_DEVICE must be auto, cpu or cuda")
        return device

    def _dtype_for_device(self, torch, device: str):
        if device != "cuda":
            return torch.float32
        major, _minor = torch.cuda.get_device_capability()
        return torch.bfloat16 if major >= 8 else torch.float16

    def _torch(self):
        try:
            import torch
        except ImportError as exc:
            raise SearchModelUnavailableError("torch is not installed") from exc
        return torch

    def _transformers(self):
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise SearchModelUnavailableError("transformers is not installed") from exc
        return AutoModelForCausalLM, AutoTokenizer

    def _is_out_of_memory(self, exc: RuntimeError) -> bool:
        message = str(exc).casefold()
        return "out of memory" in message or "cuda error: out of memory" in message

    def _raise_generation_runtime_error(self, exc: RuntimeError) -> None:
        if self._is_out_of_memory(exc):
            self._clear_cuda_cache()
            raise SearchModelUnavailableError("local search LLM ran out of memory") from exc
        logger.exception("local search LLM generation failed")
        raise SearchModelUnavailableError("local search LLM failed during generation") from exc

    def _clear_cuda_cache(self) -> None:
        try:
            torch = self._torch()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except SearchModelUnavailableError:
            return


_default_client: LocalHuggingFaceSearchIntentClient | None = None


def get_default_search_intent_client() -> LocalHuggingFaceSearchIntentClient:
    global _default_client
    if _default_client is None:
        _default_client = LocalHuggingFaceSearchIntentClient()
    return _default_client


def get_search_model_status(settings: SearchLLMSettings | None = None) -> dict[str, Any]:
    settings = settings or load_search_llm_settings()
    cls = LocalHuggingFaceSearchIntentClient
    model_key = (settings.model_id, settings.revision, settings.device)
    if not settings.enabled:
        status = "disabled"
    elif cls._loading:
        status = "loading"
    elif cls._model is not None and cls._tokenizer is not None and cls._model_key == model_key:
        status = "ready"
    elif cls._load_error is not None and cls._model_key == model_key:
        status = "failed"
    else:
        status = "unloaded"

    payload: dict[str, Any] = {
        "status": status,
        "provider": "local_huggingface",
        "model_id": settings.model_id,
        "revision_pinned": bool(settings.revision),
        "device": settings.device,
    }
    if status == "failed":
        payload["error"] = "model failed to load"
    return payload
