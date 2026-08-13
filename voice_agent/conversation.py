"""Per-session speech interpretation helpers.

These classes contain no LiveKit or provider state, which makes their
behaviour straightforward to unit test.
"""

import hashlib
import re
import time
from dataclasses import dataclass

from config import (
    FILLER_MIN_LENGTH,
    FILLER_PATTERNS,
    LANGUAGE_CODE_MAP,
    LANGUAGE_LONG_TURN_WORD_COUNT,
    LANGUAGE_SHORT_TURNS_REQUIRED,
)


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


def is_explicit_request(transcript: str) -> bool:
    """Return whether a user explicitly asks the agent to change language.

    This is intentionally lightweight and conservative: the STT provider
    supplies the target language, while this function only decides whether the
    user is making a direct language-selection request.
    """
    normalized = " ".join(transcript.lower().split())
    patterns = (
        r"\b(?:speak|talk|reply|respond|answer)\s+(?:in|to)?\s*"
        r"(?:english|hindi|tamil|telugu|kannada|malayalam|marathi|gujarati|bengali|odia|punjabi)\b",
        r"\b(?:english|hindi|tamil|telugu|kannada|malayalam|marathi|gujarati|bengali|odia|punjabi)\s+"
        r"(?:mein|me|please|please speak)\b",
        r"(?:हिंदी|अंग्रेज़ी|अंग्रेजी|तमिल|तेलुगु|कन्नड़|मराठी|ગુજરાતી|বাংলা|ਪੰਜਾਬੀ)\s*"
        r"(?:में|मे|में बोलो|बोलो|बात करो)",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


@dataclass(frozen=True)
class LanguageDecision:
    """The selected TTS language and the reason for the selection."""

    confirmed_lang: str
    pending_count: int
    switched: bool
    reason: str


class LanguagePolicy:
    """Keep spoken language stable while allowing confident switches.

    Sarvam detects language independently for every turn. This policy decides
    which detected language becomes the persistent TTS language.
    """

    def __init__(
        self,
        confirmed_lang: str,
        short_turns_required: int = LANGUAGE_SHORT_TURNS_REQUIRED,
        long_turn_word_count: int = LANGUAGE_LONG_TURN_WORD_COUNT,
    ):
        self.confirmed_lang = confirmed_lang
        self.pending_count = 0
        self._pending_lang: str | None = None
        self._short_turns_required = short_turns_required
        self._long_turn_word_count = long_turn_word_count

    def decide(self, lang: str | None, transcript: str) -> LanguageDecision:
        if not lang or lang not in LANGUAGE_CODE_MAP:
            self._reset_pending()
            return self._decision(False, "no_supported_detection")

        if is_explicit_request(transcript):
            return self._switch(lang, "explicit_request")

        if lang == self.confirmed_lang:
            self._reset_pending()
            return self._decision(False, "matches_confirmed")

        if len(transcript.split()) > self._long_turn_word_count:
            return self._switch(lang, "long_turn")

        if lang != self._pending_lang:
            self._pending_lang = lang
            self.pending_count = 1
        else:
            self.pending_count += 1

        if self.pending_count >= self._short_turns_required:
            return self._switch(lang, "two_short_turns")
        return self._decision(False, "pending_short_turn")

    def _switch(self, lang: str, reason: str) -> LanguageDecision:
        switched = lang != self.confirmed_lang
        self.confirmed_lang = lang
        self._reset_pending()
        return self._decision(switched, reason)

    def _reset_pending(self) -> None:
        self.pending_count = 0
        self._pending_lang = None

    def _decision(self, switched: bool, reason: str) -> LanguageDecision:
        return LanguageDecision(self.confirmed_lang, self.pending_count, switched, reason)


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
