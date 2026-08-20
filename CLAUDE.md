# CLAUDE.md — Voice AI Agent for Indian Schools

## Overview

Multilingual conversational voice agent for schools across India. Built on **LiveKit Agents** + **Sarvam AI** (STT/TTS/LLM). Supports 11 Indian languages with automatic detection and dynamic TTS language switching.

## Architecture

```
Browser ──WebRTC──▶ LiveKit Cloud (BVC noise cancellation)
                        │
                        ▼
              Silero VAD (framework default — speech presence, speech start/end,
              barge-in trigger) + VAD-based turn detection (`turn_detection="vad"`,
              silence-based end-of-turn; the heavyweight semantic
              `inference.TurnDetector` audio model is NOT loaded — the Railway
              trial plan caps memory at 1GB and the semantic model OOM-kills
              the process at session start)
              + DynamicEndpointing (300–800ms EMA silence backstop)
                        │
                        ▼
              Sarvam STT (saaras:v3, language="unknown")
              → auto-detects language, ~70ms latency
              → stt_node override auto-reconnects dropped WebSockets (3 attempts)
                        │
                        ▼
              TranscriptDedup (text hash + time window — drop repeated finals)
                        │
                        ▼
              LanguagePolicy (confirmed TTS language + pending short turns)
              → explicit request (regex + LLM fallback) / >5-word turn switches
                immediately; 2 short turns confirm
                        │
                        ▼
              LLM (Sarvam / OpenAI / Groq — configurable via LLM_PROVIDER)
              + Langfuse tracing (per-turn spans, LLM generation, STT)
              + language instruction injected into turn context per confirmed
                language (forces fresh generation via equivalence gate)
                        │
                        ▼
              Single Sarvam TTS instance (bulbul:v3)
              → language switched per-turn via update_options()
                (same instance + WebSocket pool for all languages, never closed
                between turns)
                        │
                        ▼
              Native Sarvam TTS stream (plugin-managed cancellation and pooling)
                        │
                        ▼
              Sarvam TTS (bulbul:v3, persistent WebSocket) → Browser
```

## Running the project

```bash
# Install dependencies
uv sync

# Set up API keys
cp .env.example .env   # edit with real keys

# Terminal 1 — token server (serves API + built frontend)
uv run python server.py

# Terminal 2 — agent worker
uv run python agent.py dev

# Terminal 3 — Serve frontend dev (port 3000, proxies /token to :8000)
cd frontend && npm run dev

# Optional: test via CLI instead of browser
uv run python agent.py console
```

## Docker / Hugging Face Spaces

`Dockerfile` is a multi-stage build for HF Spaces deployment:
1. **Stage 1** (`node:22-slim`): installs npm deps via `npm ci`, runs `npm run build`
2. **Stage 2** (`uv:python3.12-bookworm-slim`): installs ffmpeg + curl, `uv sync --frozen --no-dev`, copies built frontend

Exposes port 7860. Startup runs both `agent.py start` (background) and `uvicorn server:app` on port 7860.

## Key files

| File | Purpose |
|------|---------|
| `agent.py` | LiveKit agent, event handlers, language-policy wiring, STT/LLM node overrides, and `entrypoint` |
| `voice_agent/providers.py` | Provider validation plus Sarvam/OpenAI/Groq LLM and Sarvam STT factories |
| `voice_agent/conversation.py` | `LanguagePolicy`, explicit language-request parsing, and `TranscriptDedup` |
| `voice_agent/telemetry.py` | Optional Langfuse client configuration (timeout + opt-out) |
| `server.py` | FastAPI: GET/POST `/token` (LiveKit JWT), SPA static file serving |
| `config.py` | `LanguageConfig` dataclass, 11 languages, STT/TTS/LLM/endpointing/hysteresis constants (filler patterns defined but unused) |
| `tests/test_language_policy.py` | `LanguagePolicy` unit tests |
| `pyproject.toml` | Python deps pinned to `livekit-agents[sarvam,silero]==1.6.0`, `langfuse`, `fastapi`, etc. |
| `utils/prompts.py` | `SYSTEM_PROMPT` (voice-optimised) + `GREETING_INSTRUCTIONS` + `LANGUAGE_INSTRUCTION_TEMPLATE` |
| `utils/tools.py` | 5 `@function_tool` functions (currently commented out in agent) + Langfuse span helpers |
| `utils/summarize.py` | Rolling conversation summarization (Sarvam or OpenAI/Groq) |
| `utils/tracing.py` | `SessionTracer` class (unused — agent.py uses Langfuse directly) |
| `Dockerfile` | Multi-stage build: Node 22 frontend builder + UV Python 3.12, designed for HF Spaces |
| `frontend/src/App.tsx` | Root — `AgentSessionProvider` + `AgentUI` (visualizer, language bar, chat, controls) |
| `frontend/src/main.tsx` | React 19 entrypoint |
| `frontend/src/hooks/useTranscripts.ts` | LiveKit data channel listener — parses `{type:"transcript"}` messages |
| `frontend/src/components/LanguageBar.tsx` | 11 language chips with active highlight |
| `frontend/src/components/agents-ui/` | Agent UI components (session provider, control bar, chat transcript, audio visualizer, track controls, etc.) |
| `frontend/src/components/ai-elements/` | AI conversation/message primitives |
| `frontend/src/components/ui/` | shadcn/ui base components (button, button-group, toggle, tooltip, select, separator) |
| `frontend/src/lib/utils.ts` | `cn()` utility (clsx + tailwind-merge) |
| `frontend/package.json` | React 19, Vite 8, Tailwind v4, `@livekit/components-react`, shadcn, motion, lucide |
| `frontend/vite.config.js` | Vite + React + Tailwind plugin, `@` alias, port 3000, `/token` proxy to :8000 |
| `frontend/tsconfig.json` | TypeScript config with `@/` path alias |
| `frontend/components.json` | shadcn/ui configuration |

## Frontend

React 19 + TypeScript + Vite 8 SPA. Uses Tailwind CSS v4, shadcn/ui (Radix UI primitives), and `@livekit/components-react` for LiveKit integration.

### Component tree
```
App.tsx
└── AgentSessionProvider          — wraps SessionProvider + RoomAudioRenderer
    └── AgentUI
        ├── AgentAudioVisualizerBar — animated audio visualizer synced to agent state
        ├── LanguageBar.tsx         — 11 language chips, highlights detected language
        ├── SessionSettings.tsx     — pre-call controls: language-switch mode (Stable/Instant) + preemptive toggle
        ├── AgentChatTranscript     — auto-scrolling conversation bubbles
        ├── AgentControlBar         — mic toggle, leave room (uses track-control/toggle + disconnect primitives)
        └── StartAudioButton        — browser audio unlock prompt
```

### State management
- `useSession(tokenSource)` from `@livekit/components-react` — manages Room lifecycle via `TokenSource.endpoint('/token')`
- `useAgent()` — provides agent state (idle/listening/thinking/speaking)
- `useTranscripts.ts` — listens to LiveKit `DataReceived` events, parses `{type:"transcript", role, text, language}` messages, returns `{messages, detectedLanguage, reset}`
- Vite dev server proxies `/token` to `http://localhost:8000` so no CORS issues

### Key dependencies
- `@livekit/components-react` — `SessionProvider`, `useSession`, `useAgent`, `useRoomContext`, `RoomAudioRenderer`
- `livekit-client` — `TokenSource`, `RoomEvent`
- `motion` — animations
- `lucide-react` — icons
- `streamdown` + `@streamdown/*` — markdown rendering in chat
- `ai` — AI SDK utilities
- `radix-ui` + `shadcn` — UI primitives
- `tailwind-merge` + `class-variance-authority` + `clsx` — styling utilities
- `use-stick-to-bottom` — auto-scroll behavior

## Core patterns

### Single TTS instance (`agent.py`)
- ONE `sarvam.TTS` created in `SchoolVoiceAgent.__init__()` (defaults to `hi-IN`) — Bulbul v3 is a unified multilingual model, so one instance serves all 11 languages
- Language switches call `self._tts.update_options(target_language_code=..., speaker=...)` on the **same instance** — no new connection, no new instance, no reconnect latency
- Sarvam's plugin (v1.6.0) owns WebSocket pooling and cancellation across turns via its public `stream()` API
- `on_enter()` calls `prewarm()` before greeting; `on_exit()` calls `aclose()` and drains tracked background tasks

### TranscriptDedup (`voice_agent/conversation.py`)
Deduplicates final transcript events via MD5 text hashing + configurable time window. Prevents repeated STT finals from triggering duplicate LLM/TTS cycles.

### Language detection flow (confirmed-language policy)
1. STT runs with `language="unknown"` — Sarvam auto-detects; first detection of a turn is stored as `_detected_language`
2. `TranscriptDedup.is_duplicate(transcript)` drops repeated finals
3. `LanguagePolicy` uses the detected language only to update `confirmed_lang`
4. Explicit language requests are parsed from the transcript by regex, with a fast LLM fallback (2s timeout, never breaks the turn) for unusual phrasings
5. An explicit request or a turn longer than five words switches immediately
6. Two consecutive short turns in the same new language switch; alternating short turns reset the pending count
7. TTS always speaks `confirmed_lang`, never the raw per-turn detection
8. On switch: `update_options()` retargets the single TTS instance, and a fresh language-instruction system message is injected into the turn context — the framework's equivalence gate sees the context change and invalidates in-flight preemptive generation so the reply comes in the new language
9. Transcripts are published to the frontend via the LiveKit data channel (agent messages carry `confirmed_lang`, not STT detection)

### No filler suppression
- `FILLER_PATTERNS` in `config.py` is **defined but unused** — no `FillerFilter` exists, and the agent never drops or filters user input. The LLM sees and responds to every utterance.
- `config.py` deliberately excludes answer words like "haan", "nahi", "ji" — they are legitimate replies, not fillers
- The pattern set is kept solely as documentation of Sarvam's per-language thinking sounds (hmm/umm/achha etc.)

### LanguagePolicy
- `confirmed_lang` is the persistent TTS language for the session.
- Explicit requests switch immediately.
- A detection from a turn with more than five words switches immediately.
- Otherwise, two consecutive short turns in the same new language are required.
- Flip-flopping languages (en→ta→en) resets the pending candidate and never switches.
- `LANGUAGE_SWITCH_MODE=policy` is the default. Set it to `sarvam` to bypass this policy and use Sarvam's per-turn detection directly for TTS (explicit-request detection is skipped in that mode).
- Unit-tested in `tests/test_language_policy.py`.

### Per-session settings (frontend controls)
- The frontend `SessionSettings` card (language-switch mode + preemptive generation) ships both knobs per session via LiveKit **participant attributes**: `useSession(tokenSource, { participantAttributes: { lang_mode, preemptive } })` → `TokenSource` POSTs a protojson `TokenSourceRequest` → `server.py /token` normalizes (`_session_attributes`) and puts them in the JWT via `with_attributes()` → the entrypoint reads them with `_read_session_attributes(ctx)` (via `ctx.wait_for_participant()`).
- `lang_mode` accepts `policy`/`sarvam`; anything else (or missing) falls back to `LANGUAGE_SWITCH_MODE` env. Replaces the module-level constant with per-session `agent._lang_switch_mode`.
- `preemptive` accepts `1`/`true`/`0`/`false`; unset falls back to `PREEMPTIVE_GENERATION` env. When off, both `PreemptiveGenerationOptions.enabled` and `preemptive_tts` are `False`.
- Both values are logged at session start and recorded in the Langfuse `voice-session` root span metadata.

### Turn detection
- **VAD-based turn detection** — `turn_detection="vad"` is passed explicitly, so `AgentSession` uses Silero VAD + the dynamic endpointing backstop for end-of-turn, *not* `inference.TurnDetector()` (audio semantic+acoustic EOT model: audio encoder → LLM backbone). The semantic model loads hundreds of MB at session start and OOM-kills the 1GB-capped Railway trial container (measured: 0.79 GB baseline → 0.93 GB at session start → SIGKILL -9). VAD-based detection keeps bilingual/multilingual behavior (VAD is language-agnostic) at a fraction of the memory.
- Silero VAD is passed explicitly — `vad=silero.VAD.load()` (1.6.0 does not auto-provision a VAD; 1.6.4 did via `inference.VAD(model="silero")`, but is pinned down to 1.6.0 to avoid the 1.6.2+ memory regression)
- `EndpointingOptions(mode="dynamic", min_delay=0.3, max_delay=0.8)` — 300ms floor, 800ms cap (silence backstop; merged over the framework's tighter streaming defaults because a streaming turn detector is active, turn.py:298-311)
- `alpha=0.7` — responsive EMA for fast adaptation to speaker cadence
- `InterruptionOptions(min_duration=0.3)` — 300ms barge-in threshold, with `resume_false_interruption` + `false_interruption_timeout=2.0`
- `PreemptiveGenerationOptions(enabled=True, preemptive_tts=True, max_speech_duration=10.0, max_retries=3)` — start TTS as soon as LLM produces first tokens
- Backchannel boundary: 0.3s start, 0.8s end — suppresses spurious interruptions near speech boundaries
- For noisy environments: swap constants in `config.py` to the commented-out noisy values

### STT resilience (`agent.py:stt_node`)
- Overrides the default STT node to survive Sarvam WebSocket drops: on a retryable `APIStatusError`, replaces the dead STT with a fresh instance (`create_stt()`) and resumes after a short back-off
- Up to 3 attempts (`MAX_STT_RETRIES`) before giving up; non-retryable errors re-raise immediately

### Streaming LLM node (`agent.py:llm_node`)
- Overrides the default LLM node to add per-token observability: logs the first token with measured TTFT, counts chunks/chars, and emits a Langfuse `llm-generation` span (model, input, output, ttft_ms, token/char counts, elapsed time)

### Context management (two-layer)
When `MAX_CONTEXT_ITEMS` (50) is exceeded:
1. System prompt + rolling summary (if available) + most recent `SLIDING_WINDOW_TURNS` (10) kept verbatim
2. Older items asynchronously summarized via `utils/summarize.py` (Sarvam, OpenAI, or Groq)
3. Summary injected as a system message — agent retains full conversation context
4. If the summarizer is already busy, evicted items are buffered in `_pending_summary_items` and merged into the next run — never silently dropped
5. Background tasks are tracked for lifecycle cleanup (`track_bg` + cancel/drain in `on_exit`)

### LLM provider flexibility
- `LLM_PROVIDER` env var selects: `"sarvam"` (default), `"openai"`, or `"groq"`
- Sarvam: OpenAI-compatible `openai.LLM` at `https://api.sarvam.ai/v1` with `sarvam-105b-conversations` (livekit-sarvam plugin's hardcoded model whitelist rejects it)
- OpenAI: `livekit.plugins.openai.LLM(model="gpt-4o-mini")`
- Groq: OpenAI-compatible endpoint at `api.groq.com/openai/v1` with `openai/gpt-oss-20b`
- Provider config is validated at startup (fail-fast on missing key), with bounded SDK retries (`max_retries=2`)

### Langfuse observability
- Per-session trace with root span (`voice-session`)
- Per-turn spans (`user-turn`) with detected language, transcript length, final TTS language, policy reason, pending count
- STT spans with transcript + language metadata
- LLM generation spans with TTFT, token count, char count, elapsed time
- Tool call spans with duration + success/error (when tools are enabled)
- Events: `language-switch` (from/to, reason, mode)
- `LANGFUSE_TRACING_ENABLED=false` makes every telemetry call a no-op; `LANGFUSE_TIMEOUT` bounds requests

### Emotion handling
- Sarvam TTS has **no SSML or emotion tags** (unlike Cartesia)
- Emotion conveyed through LLM word choice + Indian interjections (see `SYSTEM_PROMPT`)
- Pace/temperature can be adjusted via `tts.update_options()` if needed, but the app relies on word choice

## Adding a new language

1. Add a `LanguageConfig` entry in `config.py`
2. Pick a Sarvam Bulbul v3 speaker for that language
3. Add the language keyword(s) to `LANGUAGE_KEYWORDS` in `voice_agent/conversation.py` for explicit-request parsing
4. The single TTS instance switches to it automatically at runtime via `update_options()`

## Adding a new tool

1. Define an async function in `utils/tools.py` with `@function_tool` decorator and `Annotated` parameters
2. Register it in `SchoolVoiceAgent.__init__()` `tools=[...]` list (currently commented out)
3. Keep tool functions fast (< 3s) for sync tools; use `asyncio.create_task()` for slow tools
4. Langfuse tool call spans are automatically created via `_get_tool_span()` / `_end_tool_span()`

## Key dependencies

### Python (`pyproject.toml`)
- `livekit-agents[sarvam,silero]==1.6.0` + `livekit-plugins-sarvam==1.6.0` + `livekit-plugins-silero==1.6.0` — LiveKit Agent framework + Sarvam/Silero plugins (pinned)
- `livekit` — server SDK (token generation)
- `fastapi` + `uvicorn[standard]` — token server + SPA serving
- `python-dotenv` — env var loading
- `langfuse>=4.0` — observability (traces, spans, generations)
- `numpy` — audio processing

### Frontend (`package.json`)
- `react` + `react-dom` v19 — UI framework
- `vite` v8 + `@vitejs/plugin-react` — build tool
- `tailwindcss` v4 + `@tailwindcss/vite` — styling
- `@livekit/components-react` — LiveKit React hooks + components
- `livekit-client` — WebRTC client
- `shadcn` + `radix-ui` — UI component primitives
- `motion` — animations
- `lucide-react` — icons
- `streamdown` + `@streamdown/*` — markdown rendering
- `ai` — AI SDK utilities
- `tailwind-merge` + `class-variance-authority` + `clsx` — styling utilities
- `use-stick-to-bottom` — auto-scroll

## Environment variables

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SARVAM_API_KEY=sk_xxxxxxxxxxxxxxxxxxxxxxxx
LLM_PROVIDER=sarvam              # "sarvam", "openai", or "groq"
OPENAI_API_KEY=sk-...            # only if LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4o-mini         # only if LLM_PROVIDER=openai
GROQ_API_KEY=gsk_...             # only if LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b  # only if LLM_PROVIDER=groq
LANGUAGE_SWITCH_MODE=policy      # "policy" (stable) or "sarvam" (raw per-turn detection)
LANGFUSE_PUBLIC_KEY=pk-lf-...    # optional: Langfuse observability
LANGFUSE_SECRET_KEY=sk-lf-...    # optional: Langfuse observability
LANGFUSE_BASE_URL=https://cloud.langfuse.com  # optional
LANGFUSE_TRACING_ENABLED=true    # set false to disable all tracing
LANGFUSE_TIMEOUT=10              # seconds
```

## Design decisions

- **Supported Sarvam lifecycle** — the agent uses only public APIs: `prewarm()`, `stream()`, `update_options()`, and `aclose()`. Sarvam plugin v1.6.0 owns cancellation and its WebSocket pool, so there is no brittle private-field access.
- **Single TTS instance** — one `sarvam.TTS` created at init; `update_options()` switches language per-turn on the same instance and WebSocket pool (Bulbul v3 is a unified multilingual model). No per-language instances, no reconnect latency on switch.
- **Confirmed-language switching** — `LanguagePolicy` ensures TTS never follows a raw one-turn detection. Explicit requests (regex + LLM fallback) and long turns switch immediately; two matching short turns are required otherwise.
- **No filler suppression** — the LLM sees every utterance; `FILLER_PATTERNS` is a vestigial constant never referenced by runtime code.
- **Transcript deduplication** — `TranscriptDedup` uses MD5 hashing + time window to prevent repeated STT finals from triggering duplicate LLM/TTS cycles.
- **Two-layer context** — Rolling summarization of older turns (async, background, length-capped) + sliding window of recent turns, with overflow buffering while the summarizer is busy. Maintains long conversation context without unbounded growth.
- **Multi-provider LLM** — `LLM_PROVIDER` env var switches between Sarvam, OpenAI, and Groq without code changes. Groq uses OpenAI-compatible API. Rolling summaries use the same selected provider.
- **Langfuse observability** — Full tracing: session → turn → STT/LLM spans + tool calls + language-switch events. TTFT tracked per LLM generation. Tracible overall latency via session span.
- **TurnHandlingOptions API** — uses the new non-deprecated `turn_handling=TurnHandlingOptions(endpointing=EndpointingOptions(...), interruption=InterruptionOptions(...), preemptive_generation=PreemptiveGenerationOptions(...))` pattern with `turn_detection="vad"` (VAD-based EOU; the semantic `inference.TurnDetector()` is avoided because it OOM-kills the 1GB-capped Railway trial container).
- **Silero VAD** — explicit `vad=silero.VAD.load()`; pinned to livekit-agents 1.6.0 to stay on the silero-plugin VAD and avoid the 1.6.2+ memory regression (1.6.0: ~700MB baseline, 1.6.4: >1GB per LiveKit community reports; local import footprint ~165MB).
- **Conversational endpointing** — `min_delay=300ms`, `max_delay=800ms`, `alpha=0.7`, `mode="dynamic"` — tuned for fast Indian-language turn-taking while tolerating natural pauses.
- **Preemptive TTS** — TTS starts as soon as LLM produces first tokens, reducing time-to-first-audio; language-instruction injection invalidates stale preemptive audio via the framework's equivalence gate.
- **STT WebSocket resilience** — `stt_node` override recreates the STT instance and resumes the session on retryable drops (up to 3 attempts) instead of tearing the job down.
- **Sync prewarm** — `on_enter()` calls `prewarm()` before generating the greeting so the first reply has no connection latency.
- **Noisy environment config** — `config.py` has commented-out overrides (300ms min endpointing, 600ms max, alpha 0.9, wider backchannel boundary) for background-noise-heavy settings.
- **React 19 + TypeScript + Tailwind v4 frontend** — `@livekit/components-react` provides session/agent hooks, shadcn/ui for consistent component styling, `TokenSource.endpoint('/token')` for auth.
- **SPA static serving** — `server.py` serves built frontend from `frontend/dist/` with SPA fallback (404 → index.html). Vite dev proxies `/token` to backend.
- **Text-based emotion** — Sarvam lacks SSML; the LLM conveys emotion through word choice and Indian interjections.
- **Data messages to frontend** — agent publishes `{type: "transcript", role, text, language}` via LiveKit data channel for chat bubbles and language highlighting; agent messages use `confirmed_lang`, not raw STT detection.
- **`linear16` codec, not mp3** — `output_audio_codec="linear16"` uses raw PCM passthrough (no per-chunk decode hop), per Sarvam's official LiveKit best-practices. `"wav"` is broken (Sarvam returns raw PCM, no WAV container) and `"mp3"` decode-glitches at chunk seams, causing stuttering audio that looks like a network issue (see livekit/agents#1454).
- **Unit tests** — `tests/test_language_policy.py` covers the confirmed-language policy (explicit requests, long-turn switching, flip-flop reset).