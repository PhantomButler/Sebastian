import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';

interface Props {
  content: string;
}

export function UserBubble({ content }: Props) {
  const colors = useTheme();

  return (
    <View style={styles.row}>
      <View style={[styles.bubble, { backgroundColor: colors.userBubbleBg }]}>
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
  text: {
    fontSize: 15,
    lineHeight: 21,
  },
});
