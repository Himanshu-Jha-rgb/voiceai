import { cn } from '@/lib/utils';
import { Toggle } from '@/components/ui/toggle';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export type LanguageSwitchMode = 'policy' | 'sarvam';
export type LlmProvider = 'sarvam' | 'openai' | 'groq';
export type PersonaKey = 'study_buddy' | 'academic_mentor' | 'parent_helpdesk' | 'quiz_master' | 'primary_tutor';

export const PROVIDER_MODELS: Record<LlmProvider, string[]> = {
  sarvam: ['sarvam-105b-conversations'],
  openai: ['gpt-4o-mini', 'gpt-4o'],
  groq: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant'],
};

export const PERSONA_OPTIONS: { key: PersonaKey; label: string; speaker: string; desc: string }[] = [
  { key: 'study_buddy', label: 'Shubh (Study Buddy)', speaker: 'shubh (Male, friendly)', desc: 'Classmate & peer companion' },
  { key: 'academic_mentor', label: 'Vidya Ma\'am (Academic Mentor)', speaker: 'meera (Female, articulate)', desc: 'Science & math mentor' },
  { key: 'parent_helpdesk', label: 'Anand (Parent Helpdesk)', speaker: 'anand (Male, professional)', desc: 'School admin & parent info' },
  { key: 'quiz_master', label: 'Aditya (Quiz Master)', speaker: 'aditya (Male, upbeat)', desc: 'Oral trivia & revision drills' },
  { key: 'primary_tutor', label: 'Maya (Primary Tutor)', speaker: 'pari (Female, soft)', desc: 'Early learning & story guide' },
];

interface SessionSettingsProps {
  langMode: LanguageSwitchMode;
  onLangModeChange: (mode: LanguageSwitchMode) => void;
  preemptive: boolean;
  onPreemptiveChange: (enabled: boolean) => void;
  llmProvider: LlmProvider;
  onLlmProviderChange: (provider: LlmProvider) => void;
  llmModel: string;
  onLlmModelChange: (model: string) => void;
  persona: PersonaKey;
  onPersonaChange: (persona: PersonaKey) => void;
  className?: string;
}

export function SessionSettings({
  langMode,
  onLangModeChange,
  preemptive,
  onPreemptiveChange,
  llmProvider,
  onLlmProviderChange,
  llmModel,
  onLlmModelChange,
  persona,
  onPersonaChange,
  className,
}: SessionSettingsProps) {
  return (
    <div
      className={cn(
        'w-full rounded-xl border border-border bg-card p-4 space-y-3',
        className,
      )}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Session settings
      </p>

      {/* Persona & Speaker Selector */}
      <div className="space-y-2">
        <p className="text-sm font-medium">Agent persona & speaker voice</p>
        <p className="text-xs text-muted-foreground">
          System prompt & Sarvam TTS speaker profile
        </p>
        <Select
          value={persona}
          onValueChange={(v) => onPersonaChange(v as PersonaKey)}
        >
          <SelectTrigger size="sm" className="w-full">
            <SelectValue>{PERSONA_OPTIONS.find((p) => p.key === persona)?.label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {PERSONA_OPTIONS.map((p) => (
              <SelectItem key={p.key} value={p.key}>
                <div className="flex flex-col text-left py-0.5">
                  <span className="font-medium text-xs">{p.label}</span>
                  <span className="text-[10px] text-muted-foreground">{p.desc} · voice: {p.speaker}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Separator />

      <div className="space-y-2">
        <p className="text-sm font-medium">LLM provider</p>
        <p className="text-xs text-muted-foreground">
          Model used for replies this call
        </p>
        <div className="flex items-center gap-2">
          <Select
            value={llmProvider}
            onValueChange={(v) => onLlmProviderChange(v as LlmProvider)}
          >
            <SelectTrigger size="sm" className="w-32">
              <SelectValue>{llmProvider}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(PROVIDER_MODELS) as LlmProvider[]).map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={llmModel} onValueChange={onLlmModelChange}>
            <SelectTrigger size="sm" className="flex-1 min-w-0">
              <SelectValue>{llmModel}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {PROVIDER_MODELS[llmProvider].map((m) => (
                <SelectItem key={m} value={m}>
                  {m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Separator />

      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">Language switching</p>
          <p className="text-xs text-muted-foreground">
            Stable (confirmed policy) vs instant (per-turn detection)
          </p>
        </div>
        <Toggle
          size="sm"
          variant="outline"
          className="w-28"
          pressed={langMode === 'policy'}
          onPressedChange={() =>
            onLangModeChange(langMode === 'policy' ? 'sarvam' : 'policy')
          }
        >
          {langMode === 'policy' ? 'Stable' : 'Instant'}
        </Toggle>
      </div>

      <Separator />

      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">Fast replies</p>
          <p className="text-xs text-muted-foreground">
            Preemptive generation — reply as soon as the LLM starts talking
          </p>
        </div>
        <Toggle
          size="sm"
          variant="outline"
          className="w-16"
          pressed={preemptive}
          onPressedChange={onPreemptiveChange}
        >
          {preemptive ? 'On' : 'Off'}
        </Toggle>
      </div>
    </div>
  );
}
