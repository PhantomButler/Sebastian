import { View, TouchableOpacity, ActivityIndicator, StyleSheet } from 'react-native';
import { SendIcon, StopCircleIcon } from '../common/Icons';
import { useTheme } from '../../theme/ThemeContext';
import type { ComposerState } from './types';

// Size of the send/stop button in dp.
const BTN_SIZE = 36;

interface Props {
  state: ComposerState;
  onPress: () => void;
}

export function SendButton({ state, onPress }: Props) {
  const colors = useTheme();
  const isDisabled =
    state === 'idle_empty' || state === 'sending' || state === 'cancelling';

  // spinner states: ActivityIndicator needs its own background circle
  if (state === 'sending' || state === 'cancelling') {
    return (
      <View style={[styles.spinnerCircle, { backgroundColor: colors.accent }]}>
        <ActivityIndicator size="small" color="#FFFFFF" />
      </View>
    );
  }

  // The SVG icons (SendIcon, StopCircleIcon) already embed a full circle in
  // their path data — sizing them to BTN_SIZE fills the tap target completely.
  const iconColor = state === 'idle_empty' ? '#AEAEB2' : colors.accent;

  return (
    <TouchableOpacity onPress={onPress} disabled={isDisabled} activeOpacity={0.8}>
      {state === 'streaming' ? (
        <StopCircleIcon size={BTN_SIZE} color={iconColor} />
      ) : (
        <SendIcon size={BTN_SIZE} color={iconColor} />
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  spinnerCircle: {
    width: BTN_SIZE,
    height: BTN_SIZE,
    borderRadius: BTN_SIZE / 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
