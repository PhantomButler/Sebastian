import { View, StyleSheet } from 'react-native';
import { ThinkButton } from './ThinkButton';
import { SendButton } from './SendButton';
import type { ComposerState } from './types';
import type { ThinkingEffort } from '../../types';

interface Props {
  state: ComposerState;
  effort: ThinkingEffort;
  onEffortChange: (next: ThinkingEffort) => void;
  onSendOrStop: () => void;
}

export function ActionsRow({ state, effort, onEffortChange, onSendOrStop }: Props) {
  return (
    <View style={styles.row}>
      <ThinkButton current={effort} onChange={onEffortChange} />
      <SendButton state={state} onPress={onSendOrStop} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 8,
    height: 36,
  },
});
