"""LLM client for Nebius Token Factory (OpenAI-compatible), with a mock backend.

Two roles are used throughout the pipeline:
  * "worker":   small Nemotron model for high-volume, latency-sensitive calls
  * "reasoner": large Nemotron model for diagnosis, repair and doc inference

Every call is logged to the evidence store so the report can show per-model usage.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from .config import Config
from .evidence import EvidenceStore

T = TypeVar("T", bound=BaseModel)

# (role, task, system, user) -> completion text
MockHandler = Callable[[str, str, str, str], str]


class LLMError(RuntimeError):
    pass


def _default_mock(role: str, task: str, system: str, user: str) -> str:
    return "{}"


def extract_json(text: str) -> str:
    """Pull a JSON object out of a model reply that may wrap it in prose or fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


class LLMClient:
    def __init__(
        self,
        cfg: Config,
        store: EvidenceStore,
        mock_handler: MockHandler | None = None,
        max_retries: int = 3,
        backoff: float = 1.0,
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.max_retries = max_retries
        self.backoff = backoff
        self._mock = mock_handler or _default_mock
        self._client = None
        if cfg.llm_backend == "openai":
            if not (cfg.api_key and cfg.base_url):
                raise LLMError("NEBIUS_API_KEY and NEBIUS_BASE_URL are required for the openai backend")
            from openai import OpenAI  # imported lazily so mock mode needs no network libs

            self._client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

    def _model_for(self, role: str) -> str:
        if role == "reasoner":
            return self.cfg.model_reasoner or "mock-reasoner"
        if role == "worker":
            return self.cfg.model_worker or "mock-worker"
        raise ValueError(f"unknown role: {role}")

    def complete(self, role: str, system: str, user: str, task: str = "") -> str:
        model = self._model_for(role)
        last_error = ""
        for attempt in range(self.max_retries):
            start = time.monotonic()
            try:
                if self._client is None:
                    text, pt, ct = self._mock(role, task, system, user), 0, 0
                else:
                    resp = self._client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.2,
                    )
                    text = resp.choices[0].message.content or ""
                    usage = getattr(resp, "usage", None)
                    pt = getattr(usage, "prompt_tokens", 0) or 0
                    ct = getattr(usage, "completion_tokens", 0) or 0
                self.store.record_llm_call(role, model, task, pt, ct, time.monotonic() - start, True)
                return text
            except Exception as exc:  # network, rate limit, server errors
                last_error = f"{type(exc).__name__}: {exc}"
                self.store.record_llm_call(
                    role, model, task, 0, 0, time.monotonic() - start, False, last_error
                )
                if attempt + 1 < self.max_retries:
                    time.sleep(self.backoff * (2**attempt))
        raise LLMError(f"{role}/{task} failed after {self.max_retries} attempts: {last_error}")

    def complete_json(self, role: str, system: str, user: str, schema: type[T], task: str = "") -> T:
        """Complete and validate against a Pydantic schema, with one repair retry."""
        text = self.complete(role, system, user, task)
        try:
            return schema.model_validate(json.loads(extract_json(text)))
        except (json.JSONDecodeError, ValidationError) as first_err:
            repair = (
                f"{user}\n\nYour previous reply was not valid for the required JSON schema "
                f"({first_err}). Reply with ONLY a corrected JSON object."
            )
            text = self.complete(role, system, repair, task + ":repair")
            try:
                return schema.model_validate(json.loads(extract_json(text)))
            except (json.JSONDecodeError, ValidationError) as second_err:
                raise LLMError(f"{task}: invalid JSON after repair: {second_err}") from second_err
