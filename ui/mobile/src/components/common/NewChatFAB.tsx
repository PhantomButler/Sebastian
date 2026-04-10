import { StyleSheet, Text, TouchableOpacity } from 'react-native';
import type { ViewStyle } from 'react-native';
import { EditIcon } from './Icons';
import { useIsDark } from '../../theme/ThemeContext';

interface Props {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  style?: ViewStyle;
}

export function NewChatFAB({ label, onPress, disabled = false, style }: Props) {
  const isDark = useIsDark();

  return (
    <TouchableOpacity
      style={[
        styles.fab,
        isDark
          ? { backgroundColor: 'rgba(70,70,70,0.95)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.22)' }
          : { backgroundColor: '#111111' },
        disabled && styles.fabDisabled,
        style,
      ]}
      onPress={disabled ? undefined : onPress}
      disabled={disabled}
      activeOpacity={0.85}
    >
      <EditIcon size={16} color="#fff" style={styles.icon} />
      <Text style={styles.label}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  fab: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 22,
    paddingVertical: 12,
    paddingHorizontal: 20,
    elevation: 4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
  },
  fabDisabled: {
    opacity: 0.5,
  },
  icon: {
    marginRight: 8,
  },
  label: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
    letterSpacing: 0.2,
  },
});
