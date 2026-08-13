"""Provider construction and startup validation.

Keeping vendor setup here prevents provider-specific behavior from leaking into
the agent's conversation lifecycle.
"""

import os
from typing import Literal

from livekit.plugins import sarvam

from config import (
    GROQ_MODEL,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    STT_FLUSH_SIGNAL,
    STT_HIGH_VAD_SENSITIVITY,
    STT_MODE,
    STT_MODEL,
    STT_SAMPLE_RATE,
)

ProviderName = Literal["sarvam", "openai", "groq"]
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def active_model() -> str:
    """Return the model name used by the selected LLM provider."""
    return {"sarvam": LLM_MODEL, "openai": OPENAI_MODEL, "groq": GROQ_MODEL}[LLM_PROVIDER]


def validate_provider_configuration() -> None:
    """Fail fast for an invalid provider or a missing required credential."""
    if LLM_PROVIDER not in {"sarvam", "openai", "groq"}:
        raise ValueError("LLM_PROVIDER must be one of: sarvam, openai, groq")

    required_key = {
        "sarvam": "SARVAM_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
    }[LLM_PROVIDER]
    if not os.getenv(required_key):
        raise RuntimeError(f"{required_key} must be set when LLM_PROVIDER={LLM_PROVIDER}")


def create_llm():
    """Build the LiveKit-compatible LLM with bounded retries and timeouts."""
    validate_provider_configuration()
    if LLM_PROVIDER == "sarvam":
        return sarvam.LLM(model=LLM_MODEL)

    from livekit.plugins.openai import LLM as OpenAILLM

    common = {"model": active_model(), "max_retries": 2}
    if LLM_PROVIDER == "groq":
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
