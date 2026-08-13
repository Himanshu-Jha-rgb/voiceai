"""Per-session speech interpretation helpers.

These classes contain no LiveKit or provider state, which makes their
behaviour straightforward to unit test.
"""

import hashlib
import time
from collections import deque

from config import FILLER_MIN_LENGTH, FILLER_PATTERNS, LANGUAGE_CODE_MAP


class FillerFilter:
    """Identify utterances that should not influence language selection."""

    @staticmethod
    def is_filler(transcript: str) -> bool:
        text = transcript.strip().lower()
        if not text or len(text) < FILLER_MIN_LENGTH or text in FILLER_PATTERNS:
            return True
        words = text.split()
        return (len(words) == 1 and len(words[0]) <= 3) or (
            len(words) == 2 and all(len(word) <= 3 for word in words)
        )


class LanguageTracker:
    """Require consecutive meaningful detections before a permanent switch."""

    def __init__(self, default_language: str, min_chars: int, consecutive_required: int):
        self._default = default_language
        self._min_chars = min_chars
        self._required = consecutive_required
        self._history: deque[tuple[str, int]] = deque(maxlen=consecutive_required)

    def record_turn(self, detected_language: str | None, transcript_length: int) -> None:
        self._history.appendleft(
            (detected_language, transcript_length)
            if detected_language and transcript_length >= self._min_chars
            else (self._default, 0)
        )

    def should_switch(self, current_language: str) -> str | None:
        if len(self._history) < self._required:
            return None
        candidate, length = self._history[0]
        if length < self._min_chars or candidate == current_language:
            return None
        if candidate not in LANGUAGE_CODE_MAP:
            return None
        if all(language == candidate and size >= self._min_chars for language, size in self._history):
            return candidate
        return None


class TranscriptDedup:
    """Drop repeated final STT events inside a short, bounded time window."""

    def __init__(self, window_seconds: float, max_history: int):
        self._window = window_seconds
        self._max = max_history
        self._seen: dict[str, float] = {}

    def is_duplicate(self, text: str) -> bool:
        if not text:
            return True
        now = time.monotonic()
        self._seen = {key: timestamp for key, timestamp in self._seen.items() if now - timestamp <= self._window}
        digest = hashlib.md5(text.strip().lower().encode()).hexdigest()
        if digest in self._seen:
            return True
        self._seen[digest] = now
        if len(self._seen) > self._max:
            oldest = min(self._seen, key=lambda key: self._seen[key])
            del self._seen[oldest]
        return False

    def reset(self) -> None:
        self._seen.clear()
