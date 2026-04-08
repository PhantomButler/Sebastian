import { View, TouchableOpacity, ActivityIndicator, StyleSheet } from 'react-native';
import { SendActionIcon, StopActionIcon } from '../common/Icons';
import { useIsDark, useTheme } from '../../theme/ThemeContext';
import type { ComposerState } from './types';

// Size of the send/stop button in dp.
const BTN_SIZE = 36;

interface Props {
  state: ComposerState;
  onPress: () => void;
}

export function SendButton({ state, onPress }: Props) {
  const colors = useTheme();
  const isDark = useIsDark();
  const isDisabled =
    state === 'idle_empty' || state === 'sending' || state === 'cancelling';
  const activeBackground = isDark ? '#FFFFFF' : '#111111';
  const activeForeground = isDark ? '#111111' : '#FFFFFF';
  const disabledBackground = colors.disabledButton;
  const disabledForeground = isDark ? '#111111' : '#FFFFFF';

  // spinner states: ActivityIndicator needs its own background circle
  if (state === 'sending' || state === 'cancelling') {
    return (
      <View style={[styles.spinnerCircle, { backgroundColor: activeBackground }]}>
        <ActivityIndicator size="small" color={activeForeground} />
      </View>
    );
  }
  const iconProps = isDisabled
    ? {
        backgroundColor: disabledBackground,
        foregroundColor: disabledForeground,
      }
    : {
        backgroundColor: activeBackground,
        foregroundColor: activeForeground,
      };

  return (
    <TouchableOpacity onPress={onPress} disabled={isDisabled} activeOpacity={0.8}>
      {state === 'streaming' ? (
        <StopActionIcon size={BTN_SIZE} {...iconProps} />
      ) : (
        <SendActionIcon size={BTN_SIZE} {...iconProps} />
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
