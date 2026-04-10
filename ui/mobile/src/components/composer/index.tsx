import { useState, useMemo, useEffect, useRef } from 'react';
import { View, StyleSheet, Alert } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
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
        {
          backgroundColor: colors.cardBackground,
          borderColor: colors.borderLight,
          shadowColor: colors.shadowColor,
        },
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
    borderWidth: 0,
    // iOS shadow
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.14,
    shadowRadius: 20,
    // Android shadow
    elevation: 8,
  },
});
