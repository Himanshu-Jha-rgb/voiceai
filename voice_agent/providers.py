"""Provider construction and startup validation.

Keeping vendor setup here prevents provider-specific behavior from leaking into
the agent's conversation lifecycle.
"""

import os
from typing import Literal

from livekit.plugins import sarvam

from config import (
    DEFAULT_GROQ_MODEL,
    GROQ_MODEL,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    PROVIDER_MODELS,
    STT_FLUSH_SIGNAL,
    STT_HIGH_VAD_SENSITIVITY,
    STT_MODE,
    STT_MODEL,
    STT_SAMPLE_RATE,
)

ProviderName = Literal["sarvam", "openai", "groq"]
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

VALID_PROVIDERS = ("sarvam", "openai", "groq")


def _env_model(provider: str) -> str:
    """Env-configured model for a provider (unvalidated raw value)."""
    return {"sarvam": LLM_MODEL, "openai": OPENAI_MODEL, "groq": GROQ_MODEL}[provider]


def resolve_provider(raw: str | None) -> str:
    """Coerce a frontend/provider string to a valid provider, else env default."""
    value = (raw or "").strip().lower()
    return value if value in VALID_PROVIDERS else LLM_PROVIDER


def resolve_model(provider: str, raw: str | None) -> str:
    """Coerce a frontend model string; fall back to the provider's env default.

    Unknown models are passed through — provider may add new models before
    this catalog is updated, so fail-soft rather than rejecting.
    """
    value = (raw or "").strip()
    return value if value else _env_model(provider)


def active_model(provider: str | None = None, model: str | None = None) -> str:
    """Return the model name for the selected LLM provider."""
    provider = resolve_provider(provider)
    return resolve_model(provider, model)


def validate_provider_configuration(provider: str | None = None) -> None:
    """Fail fast for an invalid provider or a missing required credential."""
    provider = resolve_provider(provider)
    if provider not in VALID_PROVIDERS:
        raise ValueError("LLM_PROVIDER must be one of: sarvam, openai, groq")

    required_key = {
        "sarvam": "SARVAM_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
    }[provider]
    if not os.getenv(required_key):
        raise RuntimeError(f"{required_key} must be set when LLM_PROVIDER={provider}")


def create_llm(provider: str | None = None, model: str | None = None):
    """Build the LiveKit-compatible LLM with bounded retries and timeouts.

    ``provider``/``model`` default to the env configuration ("LLM_PROVIDER" +
    provider-specific model var) so the caller can construct an LLM for a
    per-session frontend selection.
    """
    provider = resolve_provider(provider)
    validate_provider_configuration(provider)
    model = resolve_model(provider, model)

    from livekit.plugins.openai import LLM as OpenAILLM

    common = {"model": model, "max_retries": 2}
    if provider == "sarvam":
        return OpenAILLM(
            **common,
            base_url="https://api.sarvam.ai/v1",
            api_key=os.environ["SARVAM_API_KEY"],
            extra_headers={"api-subscription-key": os.environ["SARVAM_API_KEY"]},
        )
    if provider == "groq":
        return OpenAILLM(
            **common,
            base_url=GROQ_BASE_URL,
            api_key=os.environ["GROQ_API_KEY"],
        )
    return OpenAILLM(**common)


def create_stt() -> sarvam.STT:
    """Build Sarvam Saaras v3 for real-time, language-detecting transcription."""
    if not os.getenv("SARVAM_API_KEY"):
        raise RuntimeError("SARVAM_API_KEY must be set for Sarvam STT/TTS")
    return sarvam.STT(
        language="unknown",
        model=STT_MODEL,
        mode=STT_MODE,
        sample_rate=STT_SAMPLE_RATE,
        high_vad_sensitivity=STT_HIGH_VAD_SENSITIVITY,
        flush_signal=STT_FLUSH_SIGNAL,
    )
