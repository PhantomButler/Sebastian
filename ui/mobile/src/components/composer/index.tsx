import { useState, useMemo, useEffect, useRef } from 'react';
import { StyleSheet, Alert } from 'react-native';
import Animated, { useAnimatedKeyboard, useAnimatedStyle } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '../../theme/ThemeContext';
import { useComposerStore } from '../../store/composer';
import { InputTextArea } from './InputTextArea';
import { ActionsRow } from './ActionsRow';
import type { ComposerState } from './types';

export interface ComposerProps {
  /** Current session id. null when composing a new (draft) session. */
  sessionId: string | null;
  /** True while the backend is streaming a response for this session. */
  isWorking: boolean;
  onSend: (text: string, opts: { thinking: boolean }) => Promise<void>;
  onStop: () => Promise<void>;
  /** Called whenever the Composer's rendered height changes. */
  onHeightChange: (height: number) => void;
}

export function Composer({
  sessionId,
  isWorking,
  onSend,
  onStop,
  onHeightChange,
}: ComposerProps) {
  const colors = useTheme();
  const insets = useSafeAreaInsets();
  // keyboard.height is a SharedValue that animates frame-by-frame on the UI thread,
  // giving smooth keyboard-following behavior with zero JS-bridge delay.
  const keyboard = useAnimatedKeyboard();

  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const cancelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const thinkActive = useComposerStore((s) => s.getThinking(sessionId));
  const setThinking = useComposerStore((s) => s.setThinking);

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
        // onStop handles errors; if it throws, recover state
        setIsCancelling(false);
      }
      return;
    }
    if (state !== 'idle_ready') return;
    const content = text.trim();
    setText('');
    setIsSending(true);
    try {
      await onSend(content, { thinking: thinkActive });
    } catch {
      // Restore text so user doesn't lose their message
      setText(content);
    } finally {
      setIsSending(false);
    }
  }

  const isInputDisabled = state === 'sending' || state === 'cancelling';

  // bottom tracks keyboard.height on the UI thread — no JS round-trip on each frame.
  // insets.bottom is captured as a constant; re-created on orientation change via re-render.
  const animatedFloatingStyle = useAnimatedStyle(() => ({
    bottom: keyboard.height.value + insets.bottom + 8,
  }));

  return (
    <Animated.View
      style={[
        styles.floating,
        animatedFloatingStyle,
        {
          backgroundColor: colors.cardBackground,
          borderColor: colors.borderLight,
          shadowColor: colors.shadowColor,
        },
      ]}
      onLayout={(e) => {
        onHeightChange(e.nativeEvent.layout.height);
      }}
    >
      <InputTextArea
        value={text}
        onChange={setText}
        editable={!isInputDisabled}
      />
      <ActionsRow
        state={state}
        thinkActive={thinkActive}
        onThinkToggle={() => setThinking(sessionId, !thinkActive)}
        onSendOrStop={handleSendOrStop}
      />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  floating: {
    position: 'absolute',
    left: 12,
    right: 12,
    borderRadius: 24,
    padding: 12,
    borderWidth: 1,
    // iOS shadow
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 8,
    // Android shadow
    elevation: 3,
  },
});
