import { View, Text, StyleSheet } from 'react-native';
import { useIsDark, useTheme } from '../../theme/ThemeContext';
import type { Message } from '../../types';

interface Props { message: Message; }

export function MessageBubble({ message }: Props) {
  const colors = useTheme();
  const isDark = useIsDark();
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <View style={[styles.row, styles.rowUser]}>
        <View
          style={[
            styles.bubble,
            { backgroundColor: colors.userBubbleBg },
            isDark ? styles.userBubbleDark : null,
          ]}
        >
          <Text style={{ color: colors.userBubbleText }}>{message.content}</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={[styles.row, styles.rowAssistant]}>
      <Text style={{ color: colors.text }}>{message.content}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 12, paddingVertical: 4 },
  rowUser: { alignItems: 'flex-end' },
  rowAssistant: { alignItems: 'flex-start' },
  bubble: { maxWidth: '80%', borderRadius: 16, padding: 10 },
  userBubbleDark: {
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.22)',
  },
});
