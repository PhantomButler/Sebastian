import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';

interface Props {
  message: string;
  ctaLabel?: string;
  onCta?: () => void;
}

export function EmptyState({ message, ctaLabel, onCta }: Props) {
  const colors = useTheme();

  return (
    <View style={styles.container}>
      <Text style={[styles.message, { color: colors.textMuted }]}>{message}</Text>
      {ctaLabel && onCta && (
        <Text style={[styles.cta, { color: colors.accent }]} onPress={onCta}>{ctaLabel}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  message: { textAlign: 'center', marginBottom: 12 },
  cta: { fontWeight: 'bold' },
});
