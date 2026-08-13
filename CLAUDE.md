# CLAUDE.md — Voice AI Agent for Indian Schools

## Overview

Multilingual conversational voice agent for schools across India. Built on **LiveKit Agents** + **Sarvam AI** (STT/TTS/LLM). Supports 11 Indian languages with automatic detection and dynamic TTS voice switching.

## Architecture

```
Browser ──WebRTC──▶ LiveKit Cloud (BVC noise cancellation)
                        │
                        ▼
              Silero VAD (turn detection, speech start/end)
                        │
                        ▼
              Sarvam STT (saaras:v3, language="unknown")
              → auto-detects language, ~70ms latency
                        │
                        ▼
              TranscriptDedup (text hash + time window — drop repeated finals)
                        │
                        ▼
              LanguagePolicy (confirmed TTS language + pending short turns)
              → explicit / >5-word turn switches immediately; 2 short turns confirm
                        │
                        ▼
              LLM (Sarvam / OpenAI / Groq — configurable via LLM_PROVIDER)
              + Langfuse tracing (per-turn spans, LLM generation, TTS, STT)
                        │
                        ▼
              MultilingualTTS → TTSSessionManager → Sarvam TTS instance
              (persistent pool: 1 TTS per language, websockets NEVER closed per-turn)
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
1. **Stage 1** (`node:20-slim`): installs npm deps, runs `npm run build`
2. **Stage 2** (`uv:python3.12-bookworm-slim`): installs ffmpeg + curl, `uv sync --frozen`, copies built frontend

Exposes port 7860. Startup runs both `agent.py start` (background) and `uvicorn server:app` on port 7860.

## Key files

| File | Purpose |
|------|---------|
| `agent.py` | LiveKit TTS adapter, `TTSSessionManager`, `MultilingualTTS`, `SchoolVoiceAgent`, and `entrypoint` |
| `voice_agent/providers.py` | Provider validation plus Sarvam/OpenAI/Groq LLM and Sarvam STT factories |
| `voice_agent/conversation.py` | `LanguagePolicy`, explicit-request detection, filler helpers, and `TranscriptDedup` |
| `voice_agent/telemetry.py` | Optional Langfuse client configuration |
| `server.py` | FastAPI: GET/POST `/token` (LiveKit JWT), SPA static file serving |
| `config.py` | `LanguageConfig` dataclass, 11 languages, STT/TTS/LLM/endpointing/hysteresis/filler constants |
| `pyproject.toml` | Python deps: `livekit-agents[sarvam,silero]`, `langfuse`, `fastapi`, etc. |
| `utils/prompts.py` | `SYSTEM_PROMPT` (voice-optimised, ~2000 chars) + `GREETING_INSTRUCTIONS` |
| `utils/tools.py` | 5 `@function_tool` functions (currently commented out in agent) + Langfuse span helpers |
| `utils/summarize.py` | Rolling conversation summarization (Sarvam or OpenAI) |
| `utils/tracing.py` | `SessionTracer` class (unused — agent.py uses Langfuse directly) |
| `Dockerfile` | Multi-stage build: Node 20 frontend builder + UV Python 3.12, designed for HF Spaces |
| `frontend/src/App.tsx` | Root — `AgentSessionProvider` + `AgentUI` (visualizer, language bar, chat, controls) |
| `frontend/src/main.tsx` | React 19 entrypoint |
| `frontend/src/hooks/useTranscripts.ts` | LiveKit data channel listener — parses `{type:"transcript"}` messages |
| `frontend/src/components/LanguageBar.tsx` | 11 language chips with active highlight |
| `frontend/src/components/agents-ui/` | Agent UI components (session provider, control bar, chat transcript, audio visualizer, etc.) |
| `frontend/src/components/ai-elements/` | AI conversation/message primitives |
| `frontend/src/components/ui/` | shadcn/ui base components (button, toggle, tooltip, select, separator) |
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
        ├── AgentChatTranscript     — auto-scrolling conversation bubbles
        ├── AgentControlBar         — mic toggle, leave room
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

### TTS Session Manager (`agent.py:TTSSessionManager`)
Centralized owner of all TTS websocket lifecycle. Design invariants:
- ONE `sarvam.TTS` instance per language (lazily created, persistent for session lifetime)
- Sarvam's supported TTS API manages pooled WebSockets across turns
- Websockets are **never** closed between turns — only on confirmed language switch or shutdown
- `async Lock` serializes close/remove transitions
- `warm()` calls the supported `prewarm()` API

### MultilingualTTS (`agent.py:MultilingualTTS`)
- Extends `livekit.agents.tts.TTS` — drop-in TTS for LiveKit's `Agent`
- Thin adapter over `TTSSessionManager` — delegates all lifecycle decisions
- `synthesize()` → returns Sarvam `ChunkedStream` (HTTP POST, no websocket race risk)
- `stream()` → returns Sarvam's native streaming implementation
- Both retry up to `TTS_WS_MAX_RETRIES` times on transient failures

### TranscriptDedup (`voice_agent/conversation.py`)
Deduplicates final transcript events via MD5 text hashing + configurable time window. Prevents repeated STT finals from triggering duplicate LLM/TTS cycles.

### Language detection flow (confirmed-language policy)
1. STT runs with `language="unknown"` — Sarvam auto-detects
2. `user_input_transcribed` event stores detected language as `_detected_language`
3. `TranscriptDedup.is_duplicate(transcript)` drops repeated finals
4. `LanguagePolicy` uses the detected language only to update `confirmed_lang`
5. An explicit language request or a turn longer than five words switches immediately
6. Two consecutive short turns in the same new language switch; alternating short turns reset the pending count
7. TTS always speaks `confirmed_lang`, never the raw per-turn detection

### Filler suppression
- `FillerFilter.is_filler()` checks: length < 4, exact match against 30+ filler patterns, or single/dual-word very-short utterances
- When filler detected: **no LLM generation, no TTS, no state transition, no language recording**
- Patterns include: hmm, uh, okay, haan, ji, kya, nahi, achha, theek hai, etc.

### LanguagePolicy
- `confirmed_lang` is the persistent TTS language for the session.
- Explicit requests switch immediately.
- A detection from a turn with more than five words switches immediately.
- Otherwise, two consecutive short turns in the same new language are required.
- Flip-flopping languages (en→ta→en) resets the pending candidate and never switches.
- `LANGUAGE_SWITCH_MODE=policy` is the default. Set it to `sarvam` to bypass this policy and use Sarvam's per-turn detection directly for TTS.

### Turn detection
- `AgentSession(vad=silero.VAD.load())` — Silero VAD for reliable speech detection
- `EndpointingOptions(mode="dynamic", min_delay=0.05, max_delay=0.15)` — 50ms floor, 150ms cap
- `alpha=0.6` — responsive EMA for fast adaptation to speaker cadence
- `InterruptionOptions(min_duration=0.2)` — 200ms barge-in threshold
- `PreemptiveGenerationOptions(enabled=True, preemptive_tts=True)` — start TTS as soon as LLM produces first tokens
- Backchannel boundary: 300ms start, 1.5s end — suppresses spurious interruptions near speech boundaries
- For noisy environments: swap constants in `config.py` to the commented-out noisy values

### Context management (two-layer)
When `MAX_CONTEXT_ITEMS` (50) is exceeded:
1. System prompt + rolling summary (if available) + most recent `SLIDING_WINDOW_TURNS` (10) kept verbatim
2. Older items asynchronously summarized via `utils/summarize.py` (Sarvam or OpenAI)
3. Summary injected as a system message — agent retains full conversation context

### LLM provider flexibility
- `LLM_PROVIDER` env var selects: `"sarvam"` (default), `"openai"`, or `"groq"`
- Sarvam: native `sarvam.LLM(model="sarvam-30b")`
- OpenAI: `livekit.plugins.openai.LLM(model="gpt-4o-mini")`
- Groq: OpenAI-compatible endpoint at `api.groq.com/openai/v1` with `llama-3.3-70b-versatile`

### Langfuse observability
- Per-session trace with root span (`voice-session`)
- Per-turn spans (`user-turn`) with detected language, transcript length, final TTS language
- STT spans with transcript + language metadata
- LLM generation spans with TTFT, token count, char count, elapsed time
- TTS spans with TTFB tracking
- Tool call spans with duration + success/error
- Events: language-switch (temporary vs hysteresis-confirmed), interruption start/resume/cancel

### Emotion handling
- Sarvam TTS has **no SSML or emotion tags** (unlike Cartesia)
- Emotion conveyed through LLM word choice + Indian interjections (see `SYSTEM_PROMPT`)
- Pace/temperature adjustable via `tts.update_options()` per emotional context

## Adding a new language

1. Add a `LanguageConfig` entry in `config.py`
2. Pick a Sarvam Bulbul v3 speaker for that language
3. The `MultilingualTTS` pool will auto-create the TTS instance on first use

## Adding a new tool

1. Define an async function in `utils/tools.py` with `@function_tool` decorator and `Annotated` parameters
2. Register it in `SchoolVoiceAgent.__init__()` `tools=[...]` list
3. Keep tool functions fast (< 3s) for sync tools; use `asyncio.create_task()` for slow tools
4. Langfuse tool call spans are automatically created via `_get_tool_span()` / `_end_tool_span()`

## Key dependencies

### Python (`pyproject.toml`)
- `livekit-agents[sarvam,silero]>=1.5` — LiveKit Agent framework + Sarvam/Silero plugins
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
GROQ_MODEL=llama-3.3-70b-versatile  # only if LLM_PROVIDER=groq
LANGFUSE_PUBLIC_KEY=pk-lf-...    # optional: Langfuse observability
LANGFUSE_SECRET_KEY=sk-lf-...    # optional: Langfuse observability
LANGFUSE_BASE_URL=https://cloud.langfuse.com  # optional
```

## Design decisions

- **Supported Sarvam lifecycle** — `TTSSessionManager` uses only `prewarm()`, `stream()`, and `aclose()`. Sarvam plugin v1.6.4 owns cancellation and its WebSocket pool, so there is no brittle private-field access.
- **Confirmed-language switching** — `LanguagePolicy` ensures TTS never follows a raw one-turn detection. Explicit requests and long turns switch immediately; two matching short turns are required otherwise.
- **Filler suppression** — Utterances matching 30+ filler patterns or shorter than 4 characters are dropped entirely: no LLM, no TTS, no state transition. Eliminates spurious "Hmm" → full pipeline activation.
- **Transcript deduplication** — `TranscriptDedup` uses MD5 hashing + time window to prevent repeated STT finals from triggering duplicate LLM/TTS cycles.
- **Two-layer context** — Rolling summarization of older turns (async, background) + sliding window of recent turns. Maintains long conversation context without unbounded growth.
- **Multi-provider LLM** — `LLM_PROVIDER` env var switches between Sarvam, OpenAI, and Groq without code changes. Groq uses OpenAI-compatible API.
- **Langfuse observability** — Full tracing: session → turn → STT/LLM/TTS spans + tool calls + language-switch events. TTFT and TTFB tracked per generation.
- **TurnHandlingOptions API** — uses the new non-deprecated `turn_handling=TurnHandlingOptions(endpointing=EndpointingOptions(...))` pattern with preemptive generation enabled.
- **Silero VAD** — separate VAD model (`vad=silero.VAD.load()`) for reliable turn detection, following LiveKit's recommended pattern.
- **Aggressive endpointing** — `min_delay=50ms`, `max_delay=150ms`, `alpha=0.6`, `mode="dynamic"` — tuned for fast Indian-language turn-taking with minimal silence gaps.
- **Preemptive TTS** — TTS starts as soon as LLM produces first tokens, reducing time-to-first-audio.
- **TTS pool, not single TTS with `update_options()`** — avoids WebSocket reconnect latency when switching languages mid-conversation. One persistent `sarvam.TTS` per language.
- **Sync prewarm** — `MultilingualTTS.prewarm()` is synchronous to match LiveKit's `TTS` base class signature. Hot languages (hi-IN, en-IN) prewarmed on agent entry.
- **Noisy environment config** — `config.py` has commented-out overrides (300ms endpointing, 600ms max) for background-noise-heavy settings.
- **React 19 + TypeScript + Tailwind v4 frontend** — `@livekit/components-react` provides session/agent hooks, shadcn/ui for consistent component styling, `TokenSource.endpoint('/token')` for auth.
- **SPA static serving** — `server.py` serves built frontend from `frontend/dist/` with SPA fallback (404 → index.html). Vite dev proxies `/token` to backend.
- **Text-based emotion** — Sarvam lacks SSML; the LLM conveys emotion through word choice and Indian interjections.
- **Data messages to frontend** — agent publishes `{type: "transcript", role, text, language}` via LiveKit data channel for chat bubbles and language highlighting.
- **Explicit mp3 codec** — `output_audio_codec="mp3"` set explicitly; `"wav"` is blocked because Sarvam returns raw PCM bytes instead of a valid WAV container, causing LiveKit decode crashes.
- **Stale WebSocket retry** — `synthesize()` and `stream()` retry up to `TTS_WS_MAX_RETRIES` times on failure. ConnectionPool handles stale connection recovery internally.
- **`target_language_code` propagation** — `update_options()` passes `target_language_code` through to the underlying `sarvam.TTS.update_options()` so the internal opts stay consistent with the wrapper's language routing.
