import { View, Text, StyleSheet } from 'react-native';
import { useIsDark, useTheme } from '../../theme/ThemeContext';

interface Props {
  content: string;
}

export function UserBubble({ content }: Props) {
  const colors = useTheme();
  const isDark = useIsDark();

  return (
    <View style={styles.row}>
      <View
        style={[
          styles.bubble,
          { backgroundColor: colors.userBubbleBg },
          isDark ? styles.bubbleDark : null,
        ]}
      >
        <Text style={[styles.text, { color: colors.userBubbleText }]}>{content}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    paddingHorizontal: 16,
    paddingVertical: 6,
    alignItems: 'flex-end',
  },
  bubble: {
    maxWidth: '75%',
    borderRadius: 18,
    borderBottomRightRadius: 4,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  bubbleDark: {
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.22)',
  },
  text: {
    fontSize: 15,
    lineHeight: 21,
  },
});
