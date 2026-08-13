"""Optional, non-blocking Langfuse client configuration."""

import os

from langfuse import Langfuse


def create_langfuse_client() -> Langfuse:
    """Create Langfuse using explicit timeout and opt-out configuration.

    Tracing must never prevent the voice path from starting. Set
    ``LANGFUSE_TRACING_ENABLED=false`` to make every telemetry call a no-op.
    """
    enabled = os.getenv("LANGFUSE_TRACING_ENABLED", "true").lower() != "false"
    return Langfuse(
        timeout=int(os.getenv("LANGFUSE_TIMEOUT", "10")),
        tracing_enabled=enabled,
    )
