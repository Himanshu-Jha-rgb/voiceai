"""Per-session speech interpretation helpers.

These classes contain no LiveKit or provider state, which makes their
behaviour straightforward to unit test.
"""

import hashlib
import re
import time
from dataclasses import dataclass

from config import (
    LANGUAGE_CODE_MAP,
    LANGUAGE_LONG_TURN_WORD_COUNT,
    LANGUAGE_SHORT_TURNS_REQUIRED,
)


LANGUAGE_KEYWORDS: dict[str, str] = {
    "english": "en-IN",
    "अंग्रेज़ी": "en-IN",
    "अंग्रेजी": "en-IN",
    "hindi": "hi-IN",
    "हिंदी": "hi-IN",
    "tamil": "ta-IN",
    "தமிழ்": "ta-IN",
    "telugu": "te-IN",
    "తెలుగు": "te-IN",
    "kannada": "kn-IN",
    "ಕನ್ನಡ": "kn-IN",
    "malayalam": "ml-IN",
    "മലയാളം": "ml-IN",
    "marathi": "mr-IN",
    "मराठी": "mr-IN",
    "gujarati": "gu-IN",
    "ગુજરાતી": "gu-IN",
    "bengali": "bn-IN",
    "বাংলা": "bn-IN",
    "odia": "od-IN",
    "ଓଡ଼ିଆ": "od-IN",
    "punjabi": "pa-IN",
    "ਪੰਜਾਬੀ": "pa-IN",
}

_VERBS = r"(?:speak|talk|reply|respond|answer)"
_LANG_ALT = "|".join(re.escape(keyword) for keyword in LANGUAGE_KEYWORDS)

_language_patterns = (
    # verb first, latin: "speak in english", "talk to english"
    re.compile(rf"\b{_VERBS}\s+(?:in|to)?\s*({_LANG_ALT})\b", re.IGNORECASE),
    # lang first, latin: "english mein", "english me", "english please speak"
    re.compile(rf"\b({_LANG_ALT})\s+(?:mein|me|please(?:\s+speak)?)\b", re.IGNORECASE),
    # lang first, indic scripts: "अंग्रेज़ी में बोलो", "हिंदी बोलो", "বাংলা বলো",
    # "ಕನ್ನಡ ಮಾತನಾಡು", "தமிழ் பேசு"
    re.compile(rf"({_LANG_ALT})\s*(?:में|मे|बोलो|बात करो|বলো|বলুন|ಮಾತನಾಡು|ಹೇಳು|பேசு)"),
)


def extract_requested_language(transcript: str) -> str | None:
    """Return the BCP-47 code of the language a user explicitly requests.

    Unlike the previous boolean check, this parses the *requested* language
    from the transcript — the STT-detected language of the utterance may be
    the user's speaking language, not the language they ask for (e.g. a Hindi
    sentence "क्या तुम अंग्रेज़ी में बोल सकते हो?" asks for English).
    """
    normalized = " ".join(transcript.lower().split())
    for pattern in _language_patterns:
        match = pattern.search(normalized)
        if match:
            return LANGUAGE_KEYWORDS.get(match.group(1).lower())
    return None


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
        requested = extract_requested_language(transcript)
        if requested and requested in LANGUAGE_CODE_MAP:
            return self._switch(requested, "explicit_request")

        if not lang or lang not in LANGUAGE_CODE_MAP:
            self._reset_pending()
            return self._decision(False, "no_supported_detection")

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
