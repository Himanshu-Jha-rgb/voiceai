import { useEffect, useState } from 'react';
import { RoomEvent } from 'livekit-client';
import { useRoomContext } from '@livekit/components-react';

export interface TurnMetrics {
  id: string;
  timestamp: number;
  detected_language: string | null;
  final_tts_language: string;
  reason: string;
  pending_count: number;
  switched: boolean;
  previous_language: string | null;
  mode: string;
  llm?: {
    ttft_ms?: number;
    elapsed_ms?: number;
    token_count?: number;
    char_count?: number;
  } | null;
}

export interface SessionMeta {
  llm_provider?: string;
  llm_model: string;
  stt_model: string;
  tts_model: string;
  language_switch_mode: string;
  preemptive_generation: boolean;
  persona?: string;
}

const MAX_TRACKED_TURNS = 50;

/**
 * Listens for `session_meta` and `turn_metrics` messages on the LiveKit
 * data channel — the agent publishes one per user turn so the frontend can
 * show the language policy decisions and LLM latency live.
 */
export function useAgentTelemetry() {
  const room = useRoomContext();
  const [sessionMeta, setSessionMeta] = useState<SessionMeta | null>(null);
  const [turns, setTurns] = useState<TurnMetrics[]>([]);

  useEffect(() => {
    if (!room) return;

    const handleData = (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (!msg || typeof msg.type !== 'string') return;

        if (msg.type === 'session_meta') {
          setSessionMeta({
            llm_provider: msg.llm_provider,
            llm_model: msg.llm_model,
            stt_model: msg.stt_model,
            tts_model: msg.tts_model,
            language_switch_mode: msg.language_switch_mode,
            preemptive_generation: !!msg.preemptive_generation,
            persona: msg.persona,
          });
          return;
        }

        if (msg.type === 'turn_metrics') {
          const turn: TurnMetrics = {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            timestamp: Date.now(),
            detected_language: msg.detected_language ?? null,
            final_tts_language: msg.final_tts_language,
            reason: msg.reason,
            pending_count: msg.pending_count ?? 0,
            switched: !!msg.switched,
            previous_language: msg.previous_language ?? null,
            mode: msg.mode,
            llm: msg.llm ?? null,
          };
          setTurns((prev) =>
            [turn, ...prev].slice(0, MAX_TRACKED_TURNS),
          );
        }
      } catch {
        // ignore malformed messages
      }
    };

    room.on(RoomEvent.DataReceived, handleData);
    return () => {
      room.off(RoomEvent.DataReceived, handleData);
    };
  }, [room]);

  return { sessionMeta, turns };
}