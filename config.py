import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageConfig:
    code: str  # BCP-47 language code
    name: str  # Human-readable name
    tts_speaker: str  # Default Sarvam Bulbul v3 speaker
    region: str  # Indian region


SUPPORTED_LANGUAGES: list[LanguageConfig] = [
    LanguageConfig("hi-IN", "Hindi", "shubh", "North"),
    LanguageConfig("ta-IN", "Tamil", "shubh", "South"),
    LanguageConfig("te-IN", "Telugu", "shubh", "South"),
    LanguageConfig("kn-IN", "Kannada", "shubh", "South"),
    LanguageConfig("ml-IN", "Malayalam", "shubh", "South"),
    LanguageConfig("mr-IN", "Marathi", "shubh", "West"),
    LanguageConfig("gu-IN", "Gujarati", "shubh", "West"),
    LanguageConfig("bn-IN", "Bengali", "shubh", "East"),
    LanguageConfig("od-IN", "Odia", "shubh", "East"),
    LanguageConfig("pa-IN", "Punjabi", "shubh", "North"),
    LanguageConfig("en-IN", "English", "shubh", "Pan-India"),
]

LANGUAGE_CODE_MAP: dict[str, LanguageConfig] = {
    lang.code: lang for lang in SUPPORTED_LANGUAGES
}
DEFAULT_LANGUAGE = LANGUAGE_CODE_MAP["hi-IN"]

# STT
STT_MODEL = "saaras:v3"
STT_MODE = "transcribe"
STT_SAMPLE_RATE = 16000
STT_HIGH_VAD_SENSITIVITY = True
STT_FLUSH_SIGNAL = True

# TTS
TTS_MODEL = "bulbul:v3"
TTS_SAMPLE_RATE = 24000
TTS_PACE = 1.0
TTS_TEMPERATURE = 0.6
TTS_OUTPUT_BITRATE = "128k"
TTS_OUTPUT_AUDIO_CODEC = (
    "linear16"  # no per-chunk decode hop (Sarvam/LiveKit best practice). "wav" is
    # broken (raw PCM, no container) and "mp3" decode-glitches at chunk seams —
    # stuttering audio that looks like a network issue.
)
TTS_MIN_BUFFER_SIZE = (
    60  # chars before TTS synthesizes — 30 caused fragmented prosody / cracked
    # words at chunk seams (Sarvam doc: lower = faster TTFA, more fragmented
    # prosody). 60 buffers enough for natural phrase boundaries at low latency cost.
)
TTS_MAX_CHUNK_LENGTH = 150
TTS_WS_MAX_RETRIES = 2  # stale WebSocket recovery attempts

# LLM
LLM_MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-30b")  # Sarvam model name (only used when provider is "sarvam")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "sarvam")  # "sarvam", "openai", or "groq"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # OpenAI model
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # Groq model

# ── Turn detection (aggressive conversational tuning) ─────────────────────────

ENDPOINTING_MODE = "dynamic"  # "fixed" or "dynamic" — dynamic adapts to speaker cadence
ENDPOINTING_MIN_DELAY = 0.3   # 300ms minimum silence before end-of-turn
ENDPOINTING_MAX_DELAY = 0.8   # 800ms cap — longer wait for user to finish
ENDPOINTING_ALPHA = 0.7       # EMA coefficient — balanced responsiveness

# ── Preemptive generation ────────────────────────────────────────────────────
PREEMPTIVE_GENERATION = True
PREEMPTIVE_TTS = True  # start TTS as soon as LLM produces first tokens
# Note: per LiveKit docs preemptive TTS is opt-in — cancelled preemptive audio
# cuts mid-word, which can sound like packet loss. If cracks persist after the
# linear16 + min_buffer fixes, set PREEMPTIVE_TTS = False (LLM still preempts;
# TTS waits for turn commit — adds ~300ms, removes cancelled-audio artifacts).

# ── Interruption handling ────────────────────────────────────────────────────
INTERRUPTION_MIN_DURATION = (
    0.3  # 300ms minimum speech to register interruption — avoids false triggers from coughs/breaths
)
BACKCHANNEL_BOUNDARY_START = (
    0.3  # suppress interruptions 0.3s after agent starts
)
BACKCHANNEL_BOUNDARY_END = (
    0.8  # suppress interruptions 0.8s before agent ends — total window ≤1.1s to preserve barge-in
)

# ── Confirmed language policy ──────────────────────────────────────────────────
# "policy" keeps speech stable with confirmed/pending state. "sarvam" speaks
# the language Sarvam detects for each supported turn immediately.
LANGUAGE_SWITCH_MODE = os.getenv("LANGUAGE_SWITCH_MODE", "policy").strip().lower()
if LANGUAGE_SWITCH_MODE not in {"policy", "sarvam"}:
    raise ValueError("LANGUAGE_SWITCH_MODE must be either 'policy' or 'sarvam'")

# Sarvam detects each utterance, while this policy decides when that detection
# becomes the language used for speech synthesis.
LANGUAGE_LONG_TURN_WORD_COUNT = 5
LANGUAGE_SHORT_TURNS_REQUIRED = 2

# ── Filler detection (for language tracking only) ─────────────────────────────
# These patterns are NOT used to suppress responses — the LLM always sees
# and responds to everything the user says.
#
# They ARE used to prevent filler sounds ("hmm", "achha achha") from
# influencing language detection.  Without this, a stray "hmm" could be
# detected as Bengali and trigger an unwanted language switch.
#
# Only include pure thinking/sound-fillers.  Words like "haan" (yes),
# "nahi" (no), "ji" (yes) can be legitimate answers — do NOT include them.
# FILLER_MIN_LENGTH removed — classify as filler only when transcript matches FILLER_PATTERNS.
# A blanket length shortcut silently overrides explicit real answers like "ji", "no", "yes".
FILLER_PATTERNS: set[str] = {
    # English — thinking sounds only
    "hmm",
    "umm",
    "uh",
    "ah",
    "eh",
    "oh",
    "er",
    "huh",
    "huh?",
    "what?",
    "what",
    "but also",
    "so",
    "well",
    "like",
    "yeah",
    "yep",
    "nope",
    # Hindi — thinking sounds only (NOT "haan", "nahi", "ji" — those are answers)
    "hmm hmm",
    "umm hmm",
    "achha achha",
    "acha acha",
    "theek hai",
    "haan ji",
    "ji haan",
    "arre",
    "chal",
    "chalo",
    "haan haan",
    "nahi nahi",
    # Bengali — thinking sounds only (NOT "হ্যাঁ", "না" — those are answers)
    "হুম",
    "হুম হুম",
    "আচ্ছা",
    "হুহুম",
    # Gujarati — thinking sounds only (NOT "હા", "ના" — those are answers)
    "સારું",
    "અચ્છા",
    # Tamil — thinking sounds only (NOT "ஆமா", "இல்ல" — those are answers)
    "சரி",
    "அப்படியா",
    # Telugu — thinking sounds only (NOT "అవును", "కాదు" — those are answers)
    "సరే",
    "అంతే",
    # Marathi — thinking sounds only (NOT "हो", "नाही" — those are answers)
    "ठीक आहे",
    # Kannada — thinking sounds only (NOT "ಹೌದು", "ಇಲ್ಲ" — those are answers)
    "ಸರಿ",
    # Malayalam — thinking sounds only (NOT "അതെ", "ഇല്ല" — those are answers)
    "ശരി",
}

# ── Transcript deduplication ─────────────────────────────────────────────────
DEDUP_WINDOW_SECONDS = 2.0  # ignore repeated final transcripts within this window
DEDUP_MAX_HISTORY = 20  # max recent transcript hashes to track

# ── Context management ───────────────────────────────────────────────────────
MAX_CONTEXT_ITEMS = 50  # total items before summarization + trimming kicks in
SLIDING_WINDOW_TURNS = 10  # number of most-recent turns kept verbatim

# ── TTS session management ───────────────────────────────────────────────────
# Sarvam's current LiveKit plugin owns WebSocket lifecycle and pooling. The
# application uses only its public prewarm(), stream(), and aclose() APIs.

# Noisy environment — uncomment these and comment the above when background noise is present
# ENDPOINTING_MIN_DELAY = 0.3   # 300ms
# ENDPOINTING_MAX_DELAY = 0.6   # 600ms
# ENDPOINTING_ALPHA = 0.9
# BACKCHANNEL_BOUNDARY_START = 0.5
# BACKCHANNEL_BOUNDARY_END = 1.0
