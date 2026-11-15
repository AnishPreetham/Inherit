"""Runtime configuration, read from environment variables (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model_reasoner: str
    model_worker: str
    stability_runs: int
    sandbox_image: str
    sandbox_timeout: int
    sandbox_backend: str  # "docker" or "local"
    llm_backend: str  # "openai" (Token Factory or any compatible endpoint) or "mock"

    @staticmethod
    def from_env() -> "Config":
        api_key = os.getenv("NEBIUS_API_KEY", "")
        llm_backend = os.getenv("LLM_BACKEND") or ("openai" if api_key else "mock")
        return Config(
            api_key=api_key,
            base_url=os.getenv("NEBIUS_BASE_URL", ""),
            model_reasoner=os.getenv("MODEL_REASONER", ""),
            model_worker=os.getenv("MODEL_WORKER", ""),
            stability_runs=_int("STABILITY_RUNS", 20),
            sandbox_image=os.getenv("SANDBOX_IMAGE", "inherit-sandbox"),
            sandbox_timeout=_int("SANDBOX_TIMEOUT_SECONDS", 60),
            sandbox_backend=os.getenv("SANDBOX_BACKEND", "docker"),
            llm_backend=llm_backend,
        )
