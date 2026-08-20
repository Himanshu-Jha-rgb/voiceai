import { useMemo } from 'react';
import { cn } from '@/lib/utils';
import {
  Activity,
  AudioWaveform,
  ArrowRight,
  BrainCircuit,
  GitBranch,
  Languages,
  Layers,
  ScanText,
  Sparkles,
  Zap,
  Cpu,
  Timer,
} from 'lucide-react';
import type { SessionMeta, TurnMetrics } from '@/hooks/useAgentTelemetry';

const LANG_NAMES: Record<string, string> = {
  'hi-IN': 'Hindi',
  'ta-IN': 'Tamil',
  'te-IN': 'Telugu',
  'kn-IN': 'Kannada',
  'ml-IN': 'Malayalam',
  'mr-IN': 'Marathi',
  'gu-IN': 'Gujarati',
  'bn-IN': 'Bengali',
  'od-IN': 'Odia',
  'pa-IN': 'Punjabi',
  'en-IN': 'English',
};

function langName(code: string | null | undefined): string {
  if (!code) return '—';
  return LANG_NAMES[code] ?? code;
}

const PIPELINE = [
  { icon: AudioWaveform, label: 'Silero VAD' },
  { icon: ScanText, label: 'Sarvam STT' },
  { icon: Layers, label: 'Dedup' },
  { icon: GitBranch, label: 'Language Policy' },
  { icon: BrainCircuit, label: 'LLM' },
  { icon: Zap, label: 'Sarvam TTS' },
];

interface ReasonMeta {
  label: string;
  className: string;
  desc: string;
}

function reasonMeta(reason: string): ReasonMeta {
  switch (reason) {
    case 'explicit_request':
      return {
        label: 'Explicit request',
        className: 'bg-green-500/15 text-green-600 border-green-500/40',
        desc: 'User asked for the language',
      };
    case 'sarvam_per_turn':
      return {
        label: 'Sarvam per-turn',
        className: 'bg-blue-500/15 text-blue-600 border-blue-500/40',
        desc: 'Instant raw STT detection',
      };
    case 'long_turn':
      return {
        label: 'Long turn',
        className: 'bg-cyan-500/15 text-cyan-600 border-cyan-500/40',
        desc: '>5-word turn switched immediately',
      };
    case 'two_short_turns':
      return {
        label: '2 short turns',
        className: 'bg-violet-500/15 text-violet-600 border-violet-500/40',
        desc: 'Two short turns confirmed the switch',
      };
    case 'pending_short_turn':
      return {
        label: 'Pending',
        className: 'bg-amber-500/15 text-amber-600 border-amber-500/40',
        desc: `Short turn — needs 1 more (${'keep'})`,
      };
    case 'matches_confirmed':
      return {
        label: 'Consistent',
        className: 'bg-muted text-muted-foreground border-border',
        desc: 'Detection matches confirmed language',
      };
    case 'no_supported_detection':
      return {
        label: 'No detection',
        className: 'bg-muted text-muted-foreground border-border',
        desc: 'No supported language detected',
      };
    default:
      return {
        label: reason,
        className: 'bg-muted text-muted-foreground border-border',
        desc: '',
      };
  }
}

function Badge({
  label,
  className,
  icon: Icon,
  title,
  value,
}: {
  label: string;
  className?: string;
  icon?: React.ElementType;
  title?: string;
  value?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-medium truncate max-w-full',
        className ?? 'bg-card border-border text-muted-foreground',
      )}
    >
      {Icon && <Icon className="h-3 w-3 shrink-0" />}
      {label}
      {value && <span className="opacity-70">· {value}</span>}
    </span>
  );
}

function PipelineStrip() {
  return (
    <div className="flex items-center gap-1 flex-wrap justify-center text-[10px] text-muted-foreground">
      {PIPELINE.map(({ icon: Icon, label }, i, arr) => (
        <span key={label} className="flex items-center gap-1">
          {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground/50 shrink-0" />}
          <span className="inline-flex items-center gap-1 rounded border border-border bg-card px-1.5 py-0.5">
            <Icon className="h-3 w-3" />
            {label}
          </span>
        </span>
      ))}
    </div>
  );
}

function SessionBadges({ meta }: { meta: SessionMeta | null }) {
  if (!meta) {
    return (
      <p className="text-[11px] text-muted-foreground animate-pulse">
        Waiting for agent session...
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-1 justify-center">
      <Badge icon={Cpu} label={meta.llm_model} className="border-border bg-card" />
      <span className="text-muted-foreground/40 text-[11px] leading-6">|</span>
      <Badge icon={ScanText} label={meta.stt_model} className="border-border bg-card" />
      <span className="text-muted-foreground/40 text-[11px] leading-6">|</span>
      <Badge icon={AudioWaveform} label={meta.tts_model} className="border-border bg-card" />
      <Badge
        icon={GitBranch}
        label={meta.language_switch_mode === 'policy' ? 'Stable policy' : 'Instant Sarvam'}
        title="Language switch mode"
        className={
          meta.language_switch_mode === 'policy'
            ? 'border-blue-500/40 bg-blue-500/10 text-blue-600'
            : 'border-purple-500/40 bg-purple-500/10 text-purple-600'
        }
      />
      <Badge
        icon={Zap}
        label={meta.preemptive_generation ? 'Preemptive: ON' : 'Preemptive: OFF'}
        className={
          meta.preemptive_generation
            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600'
            : 'bg-muted text-muted-foreground border-border'
        }
      />
    </div>
  );
}

function TurnRow({ turn }: { turn: TurnMetrics }) {
  const reason = reasonMeta(turn.reason);
  const pendingText =
    turn.reason === 'pending_short_turn' && turn.pending_count > 0
      ? ` (${turn.pending_count}/2)`
      : '';
  return (
    <li className="flex items-start gap-2 rounded-lg border border-border bg-card px-2.5 py-2">
      <span
        className={cn(
          'mt-1 h-2 w-2 shrink-0 rounded-full',
          turn.switched ? 'bg-green-500 animate-pulse' : 'bg-muted-foreground/40',
        )}
      />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          {turn.switched && turn.previous_language ? (
            <>
              <span className="text-xs text-muted-foreground">
                {langName(turn.previous_language)}
              </span>
              <ArrowRight className="h-3 w-3 text-muted-foreground/50 shrink-0" />
            </>
          ) : null}
          <span className="text-xs font-semibold">
            {langName(turn.final_tts_language)}
          </span>
          <span className="text-[10px] text-muted-foreground">
            · detected {langName(turn.detected_language)}
          </span>
        </div>
        <div className="flex items-center gap-1 flex-wrap">
          <Badge
            label={`${reason.label}${pendingText}`}
            className={reason.className}
            title={reason.desc}
          />
        </div>
        {turn.llm && (
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            {typeof turn.llm.ttft_ms === 'number' && (
              <span>
                <Timer className="mr-0.5 inline h-2.5 w-2.5" />
                TTFT {turn.llm.ttft_ms}ms
              </span>
            )}
            {typeof turn.llm.elapsed_ms === 'number' && (
              <span>· {turn.llm.elapsed_ms}ms total</span>
            )}
            {typeof turn.llm.token_count === 'number' && (
              <span>· {turn.llm.token_count} tokens</span>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

interface AgentInsightsProps {
  sessionMeta: SessionMeta | null;
  turns: TurnMetrics[];
  className?: string;
  collapsed?: boolean;
}

export function AgentInsights({
  sessionMeta,
  turns,
  className,
  collapsed = false,
}: AgentInsightsProps) {
  const switchCount = useMemo(
    () => turns.filter((t) => t.switched).length,
    [turns],
  );
  const recentTurns = turns.slice(0, 8);

  return (
    <div
      className={cn(
        'w-full rounded-xl border border-border bg-background/60 p-3 space-y-3',
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-primary" />
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Agent insights
          </p>
          {turns.length > 0 && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-60" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
            </span>
          )}
        </div>
        {turns.length > 0 && (
          <span className="text-[10px] text-muted-foreground">
            <Languages className="mr-1 inline h-3 w-3" />
            {switchCount} switch{switchCount === 1 ? '' : 'es'}
          </span>
        )}
      </div>

      <SessionBadges meta={sessionMeta} />

      <div className="rounded-lg border border-dashed border-border/70 px-2 py-2">
        <PipelineStrip />
      </div>

      {!collapsed && (
        <>
          {recentTurns.length === 0 ? (
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground px-1">
              <Activity className="h-3.5 w-3.5 text-muted-foreground/60 animate-pulse" />
              Live turn telemetry will appear here as you talk — watch language
              policy decisions in real time.
            </div>
          ) : (
            <ul className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
              {recentTurns.map((turn) => (
                <TurnRow key={turn.id} turn={turn} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}