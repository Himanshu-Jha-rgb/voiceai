import { useState, useMemo } from 'react';
import { useSession, useAgent, type UseSessionReturn } from '@livekit/components-react';
import { TokenSource, ConnectionState } from 'livekit-client';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { AgentControlBar } from '@/components/agents-ui/agent-control-bar';
import { AgentChatTranscript } from '@/components/agents-ui/agent-chat-transcript';
import { AgentAudioVisualizerBar } from '@/components/agents-ui/agent-audio-visualizer-bar';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { LanguageBar } from '@/components/LanguageBar';
import {
  SessionSettings,
  type LanguageSwitchMode,
  type LlmProvider,
  type PersonaKey,
  PROVIDER_MODELS,
} from '@/components/SessionSettings';
import { useTranscripts } from '@/hooks/useTranscripts';
import { useAgentTelemetry } from '@/hooks/useAgentTelemetry';
import { AgentInsights } from '@/components/AgentInsights';
import { Button } from '@/components/ui/button';
import { Phone, Loader2, AlertCircle } from 'lucide-react';

const tokenSource = TokenSource.endpoint('/token');

interface AgentUIProps {
  session: UseSessionReturn;
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
}

function AgentUI({
  session,
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
}: AgentUIProps) {
  const { state: agentState } = useAgent();
  const { messages, detectedLanguage } = useTranscripts();
  const { sessionMeta, turns } = useAgentTelemetry();
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isConnected =
    session.connectionState === ConnectionState.Connected ||
    session.connectionState === ConnectionState.Reconnecting;

  const isConnectingNow =
    session.connectionState === ConnectionState.Connecting;

  const handleConnect = async () => {
    setError(null);
    setIsConnecting(true);
    try {
      await session.start();
    } catch (err) {
      console.error('Failed to start session:', err);
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to connect to agent server',
      );
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await session.end();
    } catch (err) {
      console.error('Failed to end session:', err);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-4 bg-background text-foreground space-y-6 max-w-lg mx-auto">
      {/* ── Disconnected state: Setup & Connect Card ── */}
      {!isConnected ? (
        <div className="w-full flex flex-col items-center space-y-6 text-center">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold tracking-tight">
              Voice AI Assistant
            </h1>
            <p className="text-sm text-muted-foreground">
              Multilingual agent with real-time telemetry & language policy
            </p>
          </div>

          {error && (
            <div className="w-full p-3 rounded-lg border border-destructive/50 bg-destructive/10 text-destructive text-xs flex items-center gap-2 text-left">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <AgentAudioVisualizerBar
            state="disconnected"
            size="lg"
            className="text-muted-foreground/40"
          />
          <SessionSettings
            langMode={langMode}
            onLangModeChange={onLangModeChange}
            preemptive={preemptive}
            onPreemptiveChange={onPreemptiveChange}
            llmProvider={llmProvider}
            onLlmProviderChange={onLlmProviderChange}
            llmModel={llmModel}
            onLlmModelChange={onLlmModelChange}
            persona={persona}
            onPersonaChange={onPersonaChange}
          />
          <AgentInsights
            sessionMeta={sessionMeta}
            turns={turns}
            collapsed
          />
          <Button
            size="lg"
            onClick={handleConnect}
            disabled={isConnecting || isConnectingNow}
            className="rounded-full px-8 gap-2"
          >
            {isConnecting || isConnectingNow ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                Connecting...
              </>
            ) : (
              <>
                <Phone className="h-5 w-5" />
                Start Call
              </>
            )}
          </Button>
          <p className="text-xs text-muted-foreground">
            Click to connect and start talking to your selected AI persona
          </p>
        </div>
      ) : (
        /* ── Connected: show full UI ── */
        <>
          <AgentAudioVisualizerBar
            state={agentState}
            size="lg"
            className="text-primary"
          />

          <LanguageBar detectedLanguage={detectedLanguage} />

          <AgentChatTranscript
            agentState={agentState}
            messages={messages}
            className="w-full h-[300px]"
          />

          <AgentInsights sessionMeta={sessionMeta} turns={turns} />

          <AgentControlBar
            variant="livekit"
            isConnected={isConnected}
            isChatOpen={isChatOpen}
            onIsChatOpenChange={setIsChatOpen}
            onDisconnect={handleDisconnect}
            controls={{
              microphone: true,
              camera: false,
              screenShare: false,
              chat: false,
              leave: true,
            }}
          />

          <StartAudioButton label="Start Audio" />
        </>
      )}
    </div>
  );
}

export default function App() {
  const [langMode, setLangMode] = useState<LanguageSwitchMode>('policy');
  const [preemptive, setPreemptive] = useState(true);
  const [llmProvider, setLlmProvider] = useState<LlmProvider>('groq');
  const [llmModel, setLlmModel] = useState<string>(
    PROVIDER_MODELS.groq[0],
  );
  const [persona, setPersona] = useState<PersonaKey>('study_buddy');

  const sessionOptions = useMemo(
    () => ({
      participantAttributes: {
        lang_mode: langMode,
        preemptive: preemptive ? '1' : '0',
        llm_provider: llmProvider,
        llm_model: llmModel,
        persona: persona,
      },
    }),
    [langMode, preemptive, llmProvider, llmModel, persona],
  );
  const session = useSession(tokenSource, sessionOptions);

  const handleProviderChange = (provider: LlmProvider) => {
    setLlmProvider(provider);
    setLlmModel(PROVIDER_MODELS[provider][0]);
  };

  return (
    <AgentSessionProvider session={session}>
      <AgentUI
        session={session}
        langMode={langMode}
        onLangModeChange={setLangMode}
        preemptive={preemptive}
        onPreemptiveChange={setPreemptive}
        llmProvider={llmProvider}
        onLlmProviderChange={handleProviderChange}
        llmModel={llmModel}
        onLlmModelChange={setLlmModel}
        persona={persona}
        onPersonaChange={setPersona}
      />
    </AgentSessionProvider>
  );
}
