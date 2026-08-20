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

export const PROVIDER_MODELS: Record<LlmProvider, string[]> = {
  sarvam: ['sarvam-105b-conversations'],
  openai: ['gpt-4o-mini', 'gpt-4o'],
  groq: ['qwen/qwen3.6-27b', 'llama-3.3-70b-versatile', 'openai/gpt-oss-20b'],
};

interface SessionSettingsProps {
  langMode: LanguageSwitchMode;
  onLangModeChange: (mode: LanguageSwitchMode) => void;
  preemptive: boolean;
  onPreemptiveChange: (enabled: boolean) => void;
  llmProvider: LlmProvider;
  onLlmProviderChange: (provider: LlmProvider) => void;
  llmModel: string;
  onLlmModelChange: (model: string) => void;
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
            <SelectTrigger size="sm" className="w-28">
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
