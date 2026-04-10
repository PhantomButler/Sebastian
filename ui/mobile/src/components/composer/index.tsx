import { useState, useMemo, useEffect, useRef } from 'react';
import { View, StyleSheet, Alert } from 'react-native';
import { useTheme, useIsDark } from '../../theme/ThemeContext';
import { useComposerStore } from '../../store/composer';
import type { ThinkingEffort } from '../../types';
import { InputTextArea } from './InputTextArea';
import { ActionsRow } from './ActionsRow';
import type { ComposerState } from './types';

export interface ComposerProps {
  /** Current session id. null when composing a new (draft) session. */
  sessionId: string | null;
  /** True while the backend is streaming a response for this session. */
  isWorking: boolean;
  onSend: (text: string, opts: { effort: ThinkingEffort }) => Promise<void>;
  onStop: () => Promise<void>;
}

export function Composer({
  sessionId,
  isWorking,
  onSend,
  onStop,
}: ComposerProps) {
  const colors = useTheme();
  const isDark = useIsDark();

  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const cancelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const effort = useComposerStore((s) => s.getEffort(sessionId));
  const setEffort = useComposerStore((s) => s.setEffort);

  const state: ComposerState = useMemo(() => {
    if (isCancelling) return 'cancelling';
    if (isWorking) return 'streaming';
    if (isSending) return 'sending';
    return text.trim() ? 'idle_ready' : 'idle_empty';
  }, [isCancelling, isWorking, isSending, text]);

  // Auto-exit cancelling state when backend confirms turn is done
  useEffect(() => {
    if (!isWorking && isCancelling) {
      setIsCancelling(false);
    }
  }, [isWorking, isCancelling]);

  // 5s timeout safeguard: force-recover UI if backend doesn't respond
  useEffect(() => {
    if (state !== 'cancelling') {
      if (cancelTimerRef.current) {
        clearTimeout(cancelTimerRef.current);
        cancelTimerRef.current = null;
      }
      return;
    }
    cancelTimerRef.current = setTimeout(() => {
      setIsCancelling(false);
      Alert.alert('提示', '取消可能未生效，请下拉刷新');
    }, 5000);
    return () => {
      if (cancelTimerRef.current) {
        clearTimeout(cancelTimerRef.current);
        cancelTimerRef.current = null;
      }
    };
  }, [state]);

  async function handleSendOrStop() {
    if (state === 'streaming') {
      setIsCancelling(true);
      try {
        await onStop();
      } catch {
        setIsCancelling(false);
      }
      return;
    }
    if (state !== 'idle_ready') return;
    const content = text.trim();
    setText('');
    setIsSending(true);
    try {
      await onSend(content, { effort });
    } catch {
      setText(content);
    } finally {
      setIsSending(false);
    }
  }

  const isInputDisabled = state === 'sending' || state === 'cancelling';

  return (
    <View
      style={[
        styles.container,
        isDark
          ? { backgroundColor: 'rgba(38, 38, 42, 0.82)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)' }
          : { backgroundColor: 'rgba(242, 242, 247, 0.95)', borderWidth: 1, borderColor: 'rgba(0,0,0,0.06)' },
      ]}
    >
      <InputTextArea
        value={text}
        onChange={setText}
        editable={!isInputDisabled}
      />
      <ActionsRow
        state={state}
        effort={effort}
        onEffortChange={(next) => setEffort(sessionId, next)}
        onSendOrStop={handleSendOrStop}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: 12,
    marginBottom: 12,
    borderRadius: 24,
    padding: 12,
    // iOS shadow
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    // Android shadow (low to avoid halo glow on dark backgrounds)
    elevation: 3,
  },
});
