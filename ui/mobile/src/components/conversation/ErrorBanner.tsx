import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useTheme, useIsDark } from '../../theme/ThemeContext';

interface Props {
  message: string;
  onAction: () => void;
}

export function ErrorBanner({ message, onAction }: Props) {
  const colors = useTheme();
  const isDark = useIsDark();
  return (
    <View
      style={[
        styles.container,
        { backgroundColor: colors.cardBackground, shadowColor: colors.shadowColor },
        isDark && { borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
      ]}
    >
      <Text style={styles.message}>{message}</Text>
      <TouchableOpacity onPress={onAction} style={styles.actionBtn}>
        <Text style={styles.actionText}>前往 Settings</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: 12,
    marginVertical: 8,
    padding: 16,
    borderRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.10,
    shadowRadius: 4,
    elevation: 3,
  },
  message: {
    fontSize: 14,
    lineHeight: 22,
    color: '#9A3412',
    marginBottom: 14,
  },
  actionBtn: {
    backgroundColor: '#EA580C',
    borderRadius: 8,
    paddingVertical: 9,
    paddingHorizontal: 20,
    alignSelf: 'flex-end',
  },
  actionText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
});
