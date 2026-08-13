import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, Optional, cast

from dotenv import load_dotenv

load_dotenv(override=True)

from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.voice.turn import (
    TurnHandlingOptions,
    EndpointingOptions,
    InterruptionOptions,
    PreemptiveGenerationOptions,
)
from livekit.plugins import sarvam
from livekit.agents import inference
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
# SchoolVoiceAgent
# ═══════════════════════════════════════════════════════════════════════════════

def _create_tts(language_code: str = "hi-IN") -> sarvam.TTS:
    """Create a single Sarvam TTS instance for all languages.

    Bulbul v3 is a unified multilingual model — update_options() switches the
    target language per-request on the same WebSocket pool. No separate
    instance per language is needed.
    """
    lang = LANGUAGE_CODE_MAP.get(language_code, DEFAULT_LANGUAGE)
    return sarvam.TTS(
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


class SchoolVoiceAgent(Agent):
    def __init__(self) -> None:
        # Single TTS instance — Bulbul v3 is a unified model; language is
        # switched per-turn via update_options(), not via new instances.
        self._tts = _create_tts("hi-IN")
        self._current_language: str = "hi-IN"

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
            tts=self._tts,
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
        self._tts.prewarm()
        self.session.generate_reply(instructions=GREETING_INSTRUCTIONS)

    async def on_exit(self) -> None:
        """Clean up TTS and tracked background tasks."""
        logger.info("User exiting — closing TTS")
        if self._bg_tasks:
            logger.debug(f"Draining {len(self._bg_tasks)} agent background tasks")
            for task in list(self._bg_tasks):
                if not task.done():
                    task.cancel()
            if self._bg_tasks:
                await asyncio.gather(*list(self._bg_tasks), return_exceptions=True)
        await self._tts.aclose()

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

        previous_language = self._current_language
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
            # update_options() changes language on the same WebSocket pool —
            # no new connection needed since Bulbul v3 is a unified model.
            lang = LANGUAGE_CODE_MAP.get(target_language, DEFAULT_LANGUAGE)
            self._tts.update_options(
                target_language_code=lang.code,
                speaker=lang.tts_speaker,
            )
            self._current_language = target_language
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

    # ── Resilient STT node — auto-reconnect on Sarvam WS drop ────────────────

    async def stt_node(
        self, audio: AsyncGenerator, model_settings
    ) -> AsyncGenerator:
        """Override to retry the STT stream when Sarvam drops the WebSocket.

        Sarvam's STT WS is occasionally dropped mid-session (ConnectionError
        surfaced as APIStatusError with retryable=True).  The LiveKit framework
        currently marks those sessions as recoverable=False and tears down the
        job.  This override catches that error, replaces the dead STT with a
        fresh instance, and resumes — keeping the session alive.
        """
        from livekit.agents._exceptions import APIStatusError  # noqa: PLC0415

        MAX_STT_RETRIES = 3
        attempt = 0

        while True:
            try:
                async for event in Agent.default.stt_node(self, audio, model_settings):
                    yield event
                return  # clean exit
            except APIStatusError as exc:
                attempt += 1
                if attempt > MAX_STT_RETRIES or not exc.retryable:
                    logger.error(
                        "STT stream failed (attempt %d/%d, retryable=%s): %s — giving up",
                        attempt,
                        MAX_STT_RETRIES,
                        exc.retryable,
                        exc,
                    )
                    raise
                logger.warning(
                    "STT WebSocket dropped (attempt %d/%d) — reconnecting: %s",
                    attempt,
                    MAX_STT_RETRIES,
                    exc,
                )
                # Replace the dead STT instance with a fresh one
                self._stt = create_stt()
                await asyncio.sleep(0.5 * attempt)  # brief back-off
            except Exception:
                raise  # never swallow unexpected errors

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
