import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';

interface Props { content: string; }

export function StreamingBubble({ content }: Props) {
  const colors = useTheme();

  if (!content) return null;
  return (
    <View style={styles.row}>
      <Text style={{ color: colors.text }}>{content}</Text>
      <Text style={{ color: colors.accent }}>▋</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 12, paddingVertical: 4, alignItems: 'flex-start', flexDirection: 'row', flexWrap: 'wrap' },
});
