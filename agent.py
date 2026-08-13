import asyncio
import json
import logging
import time
from collections.abc import Coroutine
from typing import Any, Optional, cast

from dotenv import load_dotenv

load_dotenv()

from livekit.agents import JobContext, WorkerOptions, cli, tts
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.voice.turn import (
    TurnHandlingOptions,
    EndpointingOptions,
    InterruptionOptions,
    PreemptiveGenerationOptions,
)
from livekit.plugins import sarvam, silero
from langfuse.types import TraceContext

from config import (
    LANGUAGE_CODE_MAP,
    DEFAULT_LANGUAGE,
    LANGUAGE_SWITCH_MODE,
    STT_MODEL,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    GROQ_MODEL,
    TTS_MODEL,
    TTS_SAMPLE_RATE,
    TTS_PACE,
    TTS_TEMPERATURE,
    TTS_OUTPUT_BITRATE,
    TTS_OUTPUT_AUDIO_CODEC,
    TTS_MIN_BUFFER_SIZE,
    TTS_MAX_CHUNK_LENGTH,
    TTS_WS_MAX_RETRIES,
    # Turn detection
    ENDPOINTING_MODE,
    ENDPOINTING_MIN_DELAY,
    ENDPOINTING_MAX_DELAY,
    ENDPOINTING_ALPHA,
    # Preemptive generation
    PREEMPTIVE_GENERATION,
    PREEMPTIVE_TTS,
    # Interruption handling
    INTERRUPTION_MIN_DURATION,
    BACKCHANNEL_BOUNDARY_START,
    BACKCHANNEL_BOUNDARY_END,
    # Transcript dedup
    DEDUP_WINDOW_SECONDS,
    DEDUP_MAX_HISTORY,
    # Context
    MAX_CONTEXT_ITEMS,
    SLIDING_WINDOW_TURNS,
)
from utils.prompts import SYSTEM_PROMPT, GREETING_INSTRUCTIONS
from utils.tools import (
    lookup_homework,
    check_attendance,
    get_school_timetable,
    search_knowledge_base,
    explain_with_example,
    active_turn_span_var,
)
from utils.summarize import summarize_conversation
from voice_agent.conversation import LanguagePolicy, TranscriptDedup
from voice_agent.providers import active_model, create_llm, create_stt
from voice_agent.telemetry import create_langfuse_client

langfuse_client = create_langfuse_client()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("school-voice-agent")
logger.setLevel(logging.INFO)


def trace_context(trace_id: str | None, parent_span_id: str | None = None) -> TraceContext | None:
    """Build Langfuse's typed trace context only when a trace is available."""
    if not trace_id:
        return None
    context: TraceContext = {"trace_id": trace_id}
    if parent_span_id:
        context["parent_span_id"] = parent_span_id
    return context


# ═══════════════════════════════════════════════════════════════════════════════
# TTS Session Manager — centralized websocket ownership
# ═══════════════════════════════════════════════════════════════════════════════

class TTSSessionManager:
    """Centralized owner of all TTS websocket sessions.

    Design invariants:
    - ONE Sarvam TTS instance per language (lazily created, persistent)
    - Sarvam's public TTS API manages its own pooled WebSocket connections
    - Async lock serializes all state transitions (create, invalidate, close)
    - NO scattered ws.close() calls — only the session manager closes websockets

    Websocket lifecycle:
    - Created: on first use of a language
    - Reused: every subsequent turn in the same language
    - Closed ONLY: confirmed language switch, idle timeout, or process shutdown
    - NEVER closed: between turns, during hysteresis pending, or on filler
    """

    def __init__(self, default_language: str = "hi-IN"):
        self._default_language = default_language
        self._tts_instances: dict[str, sarvam.TTS] = {}
        self._current_language = default_language
        self._state_lock = asyncio.Lock()

    # ── properties ──────────────────────────────────────────────────────────

    @property
    def current_language(self) -> str:
        return self._current_language

    @current_language.setter
    def current_language(self, code: str) -> None:
        if code in LANGUAGE_CODE_MAP:
            self._current_language = code
        else:
            logger.warning(
                f"Unknown language code '{code}', "
                f"falling back to {self._default_language}"
            )
            self._current_language = self._default_language

    # ── TTS instance management ─────────────────────────────────────────────

    def _get_or_create_tts(self, language_code: str) -> sarvam.TTS:
        """Get or lazily create a Sarvam TTS instance for a language.

        Instances are persistent — they live until invalidate_language() or
        aclose() is called. Sarvam manages its own connection pool internally.
        """
        if language_code in self._tts_instances:
            return self._tts_instances[language_code]

        lang = LANGUAGE_CODE_MAP.get(language_code, DEFAULT_LANGUAGE)
        logger.info(
            "Creating Sarvam TTS for %s (%s) — speaker: %s",
            lang.name,
            lang.code,
            lang.tts_speaker,
        )
        instance = sarvam.TTS(
            target_language_code=lang.code,
            model=TTS_MODEL,
            speaker=lang.tts_speaker,
            speech_sample_rate=TTS_SAMPLE_RATE,
            pace=TTS_PACE,
            temperature=TTS_TEMPERATURE,
            output_audio_bitrate=TTS_OUTPUT_BITRATE,
            output_audio_codec=TTS_OUTPUT_AUDIO_CODEC,
            min_buffer_size=TTS_MIN_BUFFER_SIZE,
            max_chunk_length=TTS_MAX_CHUNK_LENGTH,
        )
        self._tts_instances[language_code] = instance
        return instance

    async def invalidate_language(self, language_code: str) -> None:
        """Close and remove a TTS instance.

        Called ONLY on confirmed language switch (hysteresis satisfied).
        Never called during pending state, between turns, or on filler.
        """
        async with self._state_lock:
            instance = self._tts_instances.pop(language_code, None)
        if instance:
            logger.info(f"Closing TTS instance for {language_code}")
            try:
                await instance.aclose()
            except Exception as e:
                logger.warning(f"Error closing TTS for {language_code}: {e}")

    def prewarm(self) -> None:
        """Prewarm the default language TTS so first turn has a warm websocket."""
        self._get_or_create_tts(self._default_language).prewarm()

    def warm(self, language_code: str) -> None:
        """Prewarm a language through Sarvam's supported public API."""
        self._get_or_create_tts(language_code).prewarm()

    # ── stream / synthesize — the interface used by LiveKit Agent ────────────

    def synthesize(self, text: str) -> tts.ChunkedStream:
        """Non-streaming synthesis through Sarvam's public API."""
        return self._get_or_create_tts(self._current_language).synthesize(text=text)

    def stream(self):
        """Create a native Sarvam streaming session.

        Version 1.6.4 handles cancellation and pooled-WebSocket cleanup, so
        no private-pool access or custom stream wrapper is required.
        """
        return self._get_or_create_tts(self._current_language).stream()

    async def aclose(self) -> None:
        """Close all TTS instances.  Idempotent — safe to call multiple times.

        Sarvam closes its active streams and pooled connections itself.
        """
        async with self._state_lock:
            instances = list(self._tts_instances.values())
            self._tts_instances.clear()
        if not instances:
            return
        for inst in instances:
            try:
                await inst.aclose()
            except Exception as e:
                logger.warning(f"Error during TTS shutdown: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# Multilingual TTS adapter (LiveKit TTS interface)
# ═══════════════════════════════════════════════════════════════════════════════

class MultilingualTTS(tts.TTS):
    """LiveKit TTS adapter backed by TTSSessionManager.

    Implements the tts.TTS interface that LiveKit's Agent framework expects.
    Delegates all websocket/stream management to TTSSessionManager for proper
    ownership and race-free lifecycle.
    """

    def __init__(self, session_manager: TTSSessionManager):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=1,
        )
        self._session = session_manager

    @property
    def current_language(self) -> str:
        return self._session.current_language

    @current_language.setter
    def current_language(self, code: str) -> None:
        self._session.current_language = code

    def synthesize(self, text: str, *, conn_options=None) -> tts.ChunkedStream:
        """Non-streaming synthesis.  Retries on transient failures."""
        last_exc = None
        for attempt in range(TTS_WS_MAX_RETRIES + 1):
            try:
                return self._session.synthesize(text=text)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    f"TTS synthesize attempt {attempt + 1} failed: {exc}"
                )
        raise last_exc  # type: ignore[misc]

    def stream(self, *, conn_options=None):
        """Streaming synthesis through the native, updated Sarvam stream."""
        last_exc = None
        for attempt in range(TTS_WS_MAX_RETRIES + 1):
            try:
                return self._session.stream()
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    f"TTS stream attempt {attempt + 1} failed: {exc}"
                )
        raise last_exc  # type: ignore[misc]

    async def update_options(
        self,
        *,
        target_language_code: Optional[str] = None,
        speaker: Optional[str] = None,
        pace: Optional[float] = None,
        temperature: Optional[float] = None,
    ) -> None:
        if target_language_code:
            self.current_language = target_language_code
        # The underlying TTS instance is managed by the session — update_options
        # on the active instance is called through the delegate when needed.

    def prewarm(self) -> None:
        self._session.prewarm()

    async def aclose(self) -> None:
        await self._session.aclose()


# ═══════════════════════════════════════════════════════════════════════════════
# SchoolVoiceAgent
# ═══════════════════════════════════════════════════════════════════════════════

class SchoolVoiceAgent(Agent):
    def __init__(self) -> None:
        # Centralized TTS session manager — owns all websocket lifecycle
        self._tts_session = TTSSessionManager(default_language="hi-IN")
        self._multilingual_tts = MultilingualTTS(self._tts_session)

        self._rolling_summary: Optional[str] = None
        self._summary_in_progress: bool = False

        self._session_trace_id: str | None = None
        self._root_span_id: str | None = None
        self._active_turn_span_id: str | None = None
        self._stt_span: Any | None = None

        # Per-turn state (was module-level — moved here for concurrent session safety)
        self._detected_language: Optional[str] = None
        self._detected_transcript: str = ""
        self._transcript_dedup = TranscriptDedup(DEDUP_WINDOW_SECONDS, DEDUP_MAX_HISTORY)

        self._language_policy = LanguagePolicy(confirmed_lang="hi-IN")

        # Tracked background tasks — bounded concurrency, cleanup-aware
        self._bg_tasks: set[asyncio.Task] = set()

        llm = create_llm()
        logger.info("Using %s LLM — model: %s", LLM_PROVIDER.title(), active_model())

        super().__init__(
            instructions=SYSTEM_PROMPT,
            stt=create_stt(),
            llm=llm,
            tts=self._multilingual_tts,
            tools=[
                # lookup_homework,
                # check_attendance,
                # get_school_timetable,
                # search_knowledge_base,
                # explain_with_example,
            ],
        )

    def track_bg(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Track a background task for cleanup-aware lifecycle."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def on_enter(self) -> None:
        logger.info("User entered — generating greeting")
        # Prewarm only hot languages to avoid socket explosion from 11 pools
        HOT_LANGUAGES = ["hi-IN", "en-IN"]
        for lang in HOT_LANGUAGES:
            self._tts_session.warm(lang)
        self.session.generate_reply(instructions=GREETING_INSTRUCTIONS)

    async def on_exit(self) -> None:
        """Clean up all TTS websocket sessions and tracked tasks."""
        logger.info("User exiting — closing TTS session manager")
        # Drain tracked background tasks before closing TTS
        if self._bg_tasks:
            logger.debug(f"Draining {len(self._bg_tasks)} agent background tasks")
            for task in list(self._bg_tasks):
                if not task.done():
                    task.cancel()
            if self._bg_tasks:
                await asyncio.gather(*list(self._bg_tasks), return_exceptions=True)
        await self._tts_session.aclose()

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        turn_span = langfuse_client.start_observation(
            name="user-turn",
            trace_context=trace_context(self._session_trace_id, self._root_span_id),
        )
        self._active_turn_span_id = turn_span.id
        active_turn_span_var.set({"trace_id": self._session_trace_id or "", "span_id": turn_span.id})

        transcript = self._detected_transcript or ""
        transcript_length = len(transcript)

        logger.info(
            f"Turn completed — detected language: {self._detected_language}, "
            f"transcript: {transcript[:60]!r} ({transcript_length} chars)"
        )

        previous_language = self._tts_session.current_language
        if LANGUAGE_SWITCH_MODE == "sarvam":
            # Direct mode delegates language choice to Sarvam's per-turn STT
            # detection, while preserving the current language for unknown or
            # unsupported results.
            target_language = (
                self._detected_language
                if self._detected_language in LANGUAGE_CODE_MAP
                else previous_language
            )
            decision_reason = "sarvam_per_turn"
            pending_count = 0
            switched = target_language != previous_language
        else:
            # Policy mode: Sarvam detects every turn, but the policy decides
            # when that result becomes the persistent TTS language.
            decision = self._language_policy.decide(self._detected_language, transcript)
            target_language = decision.confirmed_lang
            decision_reason = decision.reason
            pending_count = decision.pending_count
            switched = decision.switched

        if switched:
            langfuse_client.create_event(
                name="language-switch",
                trace_context=trace_context(self._session_trace_id, self._active_turn_span_id),
                metadata={
                    "from": previous_language,
                    "to": target_language,
                    "reason": decision_reason,
                    "mode": LANGUAGE_SWITCH_MODE,
                }
            )
            logger.info(
                "Language switched: %s → %s (mode=%s, reason=%s)",
                previous_language,
                target_language,
                LANGUAGE_SWITCH_MODE,
                decision_reason,
            )
        elif (
            LANGUAGE_SWITCH_MODE == "policy"
            and self._detected_language
            and self._detected_language != target_language
        ):
            logger.info(
                "Language detection %s is pending; speaking confirmed language %s "
                "(pending_count=%s)",
                self._detected_language,
                target_language,
                pending_count,
            )

        self._tts_session.current_language = target_language
        
        turn_span.update(metadata={
            "detected_language": self._detected_language,
            "transcript_length": transcript_length,
            "final_tts_language": target_language,
            "language_switch_mode": LANGUAGE_SWITCH_MODE,
            "language_policy_reason": decision_reason,
            "language_pending_count": pending_count,
        })

        # ── Step 4: Reset per-turn state ──────────────────────────────────
        self._detected_language = None
        self._detected_transcript = ""

        # ── Step 5: Two-layer chat context assembly ─────────────────────────
        items = self._chat_ctx.items
        if len(items) > MAX_CONTEXT_ITEMS:
            system_item = items[0]

            keep_count = SLIDING_WINDOW_TURNS * 2
            recent_items = (
                items[-keep_count:] if len(items) > keep_count else items[1:]
            )
            old_items = (
                items[1:-keep_count] if len(items) - 1 > keep_count else []
            )

            new_items = [system_item]

            if self._rolling_summary:
                new_items.append(
                    ChatMessage(
                        role="system",
                        content=[f"## Earlier conversation\n{self._rolling_summary}"],
                    )
                )

            new_items.extend(recent_items)

            await self.update_chat_ctx(ChatContext(new_items))
            logger.info(
                f"Two-layer context: summary={bool(self._rolling_summary)}, "
                f"recent_turns={len(recent_items) // 2}"
            )

            if old_items and not self._summary_in_progress:
                self._summary_in_progress = True
                self.track_bg(
                    self._generate_rolling_summary(old_items)
                )

    # ── Streaming LLM node — per-token logging (framework already streams) ──

    def llm_node(self, chat_ctx, tools, model_settings):
        """Override to add per-token streaming verification logs.

        The LiveKit framework already streams token-by-token from the OpenAI
        API into the TTS stream (verified in Agent.default.llm_node +
        Agent.default.tts_node).  This override adds observability so we can
        prove that LLM tokens arrive incrementally and the first token is
        not delayed by full response buffering.
        """
        return self._streaming_llm_node(chat_ctx, tools, model_settings)

    async def _streaming_llm_node(self, chat_ctx, tools, model_settings):
        chunk_count = 0
        char_count = 0
        first_content = True
        start = time.perf_counter()
        
        generation = None
        if hasattr(self, "_active_turn_span_id"):
            inp = []
            if hasattr(chat_ctx, "messages"):
                messages = chat_ctx.messages() if callable(chat_ctx.messages) else chat_ctx.messages
                messages = cast(list[Any], messages)
                for m in messages:
                    if isinstance(m.content, str):
                        inp.append({"role": getattr(m, "role", "unknown"), "content": m.content})
                    elif isinstance(m.content, list):
                        content_str = " ".join(str(getattr(c, "text", c)) for c in m.content)
                        inp.append({"role": getattr(m, "role", "unknown"), "content": content_str})
            generation = langfuse_client.start_observation(
                as_type="generation",
                name="llm-generation",
                model=active_model(),
                input=inp,
                trace_context=trace_context(self._session_trace_id, self._active_turn_span_id),
            )

        full_response_text = ""

        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            chunk_count += 1
            now = time.perf_counter()

            # Extract text from the chunk (str or ChatChunk with delta)
            text = None
            if isinstance(chunk, str):
                text = chunk
            elif hasattr(chunk, "delta"):
                delta = getattr(chunk, "delta", None)
                text = getattr(delta, "content", None)

            if text:
                char_count += len(text)
                full_response_text += text
                if first_content:
                    first_content = False
                    ttft = (now - start) * 1000
                    if generation:
                        generation.update(metadata={"ttft_ms": ttft})
                    logger.info(
                        f"LLM_FIRST_TOKEN: {text[:40]!r} "
                        f"llm_ttft_ms={round(ttft)} "
                        f"chunk={chunk_count}"
                    )

            yield chunk

        elapsed = (time.perf_counter() - start) * 1000
        if generation:
            generation.update(
                output=full_response_text,
                metadata={
                    "token_count": chunk_count,
                    "char_count": char_count,
                    "elapsed_ms": elapsed,
                }
            )
            generation.end()
        logger.info(
            f"LLM stream complete: chunks={chunk_count} "
            f"chars={char_count} elapsed_ms={round(elapsed)}"
        )

    async def _generate_rolling_summary(self, old_items: list) -> None:
        try:
            summary = await summarize_conversation(old_items, LLM_PROVIDER)
            if summary:
                self._rolling_summary = summary
                logger.info(f"Rolling summary updated ({len(summary)} chars)")
        except Exception as e:
            logger.warning(f"Rolling summary generation failed: {e}")
        finally:
            self._summary_in_progress = False


# ═══════════════════════════════════════════════════════════════════════════════
# Entrypoint
# ═══════════════════════════════════════════════════════════════════════════════

async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"User connected to room: {ctx.room.name}")

    session_trace_id = langfuse_client.create_trace_id()
    
    root_span = langfuse_client.start_observation(
        name="voice-session",
        trace_context=trace_context(session_trace_id),
        metadata={
            "room": ctx.room.name,
            "llm_model": active_model(),
            "stt_model": STT_MODEL,
            "tts_model": TTS_MODEL,
        }
    )

    agent = SchoolVoiceAgent()
    agent._session_trace_id = session_trace_id
    agent._root_span_id = root_span.id
    agent._active_turn_span_id = root_span.id
    active_turn_span_var.set({"trace_id": session_trace_id, "span_id": root_span.id})

    session = AgentSession(
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            endpointing=EndpointingOptions(
                mode=ENDPOINTING_MODE,
                min_delay=ENDPOINTING_MIN_DELAY,   # 50ms — aggressive floor
                max_delay=ENDPOINTING_MAX_DELAY,   # 150ms — tight cap (was 250ms)
                alpha=ENDPOINTING_ALPHA,           # 0.6 — responsive EMA (was 0.7)
            ),
            interruption=InterruptionOptions(
                enabled=True,
                min_duration=INTERRUPTION_MIN_DURATION,  # 200ms barge-in
                min_words=0,
                discard_audio_if_uninterruptible=True,
                resume_false_interruption=True,
                false_interruption_timeout=2.0,
                backchannel_boundary=(
                    BACKCHANNEL_BOUNDARY_START,  # 300ms
                    BACKCHANNEL_BOUNDARY_END,    # 1.5s
                ),
            ),
            preemptive_generation=PreemptiveGenerationOptions(
                enabled=PREEMPTIVE_GENERATION,
                preemptive_tts=PREEMPTIVE_TTS,
                max_speech_duration=10.0,
                max_retries=3,
            ),
        ),
    )

    @session.on("user_input_transcribed")
    def _on_stt(ev):
        transcript = getattr(ev, "transcript", "")
        language = getattr(ev, "language", None)
        is_final = getattr(ev, "is_final", False)

        if transcript and not is_final:
            if agent._stt_span is None:
                if hasattr(agent, "_active_turn_span_id") and agent._active_turn_span_id:
                    agent._stt_span = langfuse_client.start_observation(
                        name="stt",
                        trace_context=trace_context(agent._session_trace_id, agent._active_turn_span_id),
                    )

        if is_final:
            if agent._stt_span:
                agent._stt_span.update(metadata={
                    "transcript": transcript,
                    "language": language,
                    "is_final": is_final,
                    "transcript_length": len(transcript)
                })
                agent._stt_span.end()
                agent._stt_span = None
            logger.debug(f"STT final — '{transcript[:50]}' lang={language}")

        # First language detection for this turn wins
        if language and agent._detected_language is None:
            agent._detected_language = language

        if transcript and is_final:
            # Deduplicate: ignore repeated finals within the time window
            if agent._transcript_dedup.is_duplicate(transcript):
                logger.debug(
                    f"Duplicate final transcript dropped: '{transcript[:40]}'"
                )
                return

            agent._detected_transcript = (
                agent._detected_transcript + " " + transcript
            ).strip()

            agent.track_bg(
                ctx.room.local_participant.publish_data(
                    payload=json.dumps({
                        "type": "transcript",
                        "role": "user",
                        "text": transcript,
                        "language": language,
                    }),
                    reliable=True,
                )
            )

    @session.on("speech_created")
    def _on_speech_created(ev):
        logger.debug("Agent speech created")

    @session.on("conversation_item_added")
    def _on_conversation_item(ev):
        item = getattr(ev, "item", None)
        if item and getattr(item, "role", None) == "assistant":
            text_parts = []
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None)
                if t:
                    text_parts.append(str(t))
            text = " ".join(text_parts)
            if text:
                logger.debug(f"Agent response: '{text[:100]}...'")
                agent.track_bg(
                    ctx.room.local_participant.publish_data(
                        payload=json.dumps({
                            "type": "transcript",
                            "role": "agent",
                            "text": text,
                        }),
                        reliable=True,
                    )
                )

    @session.on("agent_state_changed")
    def _on_agent_state(ev):
        logger.info(f"Agent state: {ev.old_state} → {ev.new_state}")

    @session.on("error")
    def _on_error(ev):
        logger.error(f"Agent session error: {ev}")

    # session.start() returns when the session ends.  on_exit() fires
    # as part of session teardown and handles TTS cleanup.  No finally
    # block here — it would fire prematurely in console mode where
    # session.start() may return before the agent finishes its first turn.
    await session.start(
        agent=agent,
        room=ctx.room,
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
