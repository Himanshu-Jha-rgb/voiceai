import logging
import os
from typing import Optional

logger = logging.getLogger("school-voice-agent")

# Hard cap for the accumulated rolling summary — prevents unbounded growth
# across many summarization cycles.
SUMMARY_MAX_CHARS = 1200

_SUMMARIZATION_PROMPT = (
    "Summarise the following conversation turns in 2-3 sentences. "
    "Keep every important fact: the user's role (student/parent/teacher), "
    "grade/class, board, subject, topic being discussed, problems solved, "
    "and any personal details the user shared. "
    "This summary will be fed back to the AI so it remembers the full context.\n"
    "If a PREVIOUS SUMMARY is provided, do not discard it: merge its facts "
    "with the new turns into ONE combined summary. The result must stay "
    "compact (2-3 sentences) while preserving every fact from both."
)


def _format_items_as_text(items: list) -> str:
    """Convert a list of ChatMessage items to flat text for summarization."""
    lines = []
    for item in items:
        role = getattr(item, "role", "unknown")
        text = ""
        content = getattr(item, "content", None)
        if isinstance(content, list):
            for part in content:
                t = getattr(part, "text", None)
                if t:
                    text += str(t) + " "
        elif isinstance(content, str):
            text = content
        else:
            text = str(getattr(item, "text", "") or "")
        text = text.strip()
        if text:
            label = {"user": "User", "assistant": "Assistant", "system": "Context"}.get(role, "Context")
            lines.append(f"{label}: {text[:200]}")
    return "\n".join(lines)


async def summarize_conversation(
    items: list,
    llm_provider: str = "sarvam",
    previous_summary: Optional[str] = None,
) -> Optional[str]:
    """Produce a 2-3 sentence summary of older conversation items.

    When ``previous_summary`` is given, it is fed back into the summarization
    prompt and merged with the new items — so context accumulates instead of
    being overwritten by the latest chunk. Returns ``None`` if summarization
    fails or isn't available — the caller should gracefully degrade to the
    sliding-window-only fallback.
    """
    text = _format_items_as_text(items)
    if not text.strip():
        return previous_summary  # nothing new — keep what we already have

    if previous_summary:
        text = (
            f"PREVIOUS SUMMARY (preserve every fact from it):\n"
            f"{previous_summary}\n\nNEW TURNS:\n{text}"
        )

    logger.info(f"Generating rolling summary from {len(items)} items ({len(text)} chars)")

    try:
        if llm_provider in {"openai", "groq"}:
            summary = await _summarize_openai_compatible(text, llm_provider)
        else:
            summary = await _summarize_sarvam(text)
    except Exception as e:
        logger.warning(f"Rolling summary failed: {e}")
        return None

    if not summary:
        return None

    # Hard cap so the merged summary can't grow unboundedly across cycles.
    if len(summary) > SUMMARY_MAX_CHARS:
        summary = summary[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + " …"
        logger.warning(
            f"Rolling summary exceeded {SUMMARY_MAX_CHARS} chars — truncated"
        )
    return summary


async def _summarize_openai_compatible(text: str, provider: str) -> Optional[str]:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("openai package not available for summarization")
        return None

    is_groq = provider == "groq"
    api_key_name = "GROQ_API_KEY" if is_groq else "OPENAI_API_KEY"
    api_key = os.getenv(api_key_name)
    if not api_key:
        logger.warning("%s not set — cannot create a rolling summary", api_key_name)
        return None

    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1" if is_groq else None,
        max_retries=2,
        timeout=20,
    )
    response = await client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b") if is_groq else os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": _SUMMARIZATION_PROMPT},
            {"role": "user", "content": text},
        ],
        max_tokens=300,
        temperature=0.3,
    )
    summary = response.choices[0].message.content
    logger.debug("%s summary (%s chars): %s...", provider.title(), len(summary or ""), (summary or "")[:120])
    return summary


async def _summarize_sarvam(text: str) -> Optional[str]:
    """Use Sarvam AI's chat API for summarization."""
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        logger.warning("SARVAM_API_KEY not set — cannot use Sarvam for summarization")
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.sarvam.ai/v1/chat/completions",
                headers={
                    "api-subscription-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": os.getenv("SARVAM_LLM_MODEL", "sarvam-105b-conversations"),
                    "messages": [
                        {"role": "system", "content": _SUMMARIZATION_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            summary = data["choices"][0]["message"]["content"]
            logger.debug(f"Sarvam summary ({len(summary)} chars): {summary[:120]}...")
            return summary
    except ImportError:
        logger.warning("httpx not available — cannot call Sarvam API for summarization")
        return None
    except Exception as e:
        logger.warning(f"Sarvam summarization failed: {e}")
        return None
