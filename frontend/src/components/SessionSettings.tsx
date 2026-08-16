import { cn } from '@/lib/utils';
import { Toggle } from '@/components/ui/toggle';
import { Separator } from '@/components/ui/separator';

export type LanguageSwitchMode = 'policy' | 'sarvam';

interface SessionSettingsProps {
  langMode: LanguageSwitchMode;
  onLangModeChange: (mode: LanguageSwitchMode) => void;
  preemptive: boolean;
  onPreemptiveChange: (enabled: boolean) => void;
  className?: string;
}

export function SessionSettings({
  langMode,
  onLangModeChange,
  preemptive,
  onPreemptiveChange,
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
