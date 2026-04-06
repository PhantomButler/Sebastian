import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';

export function MemorySection() {
  const colors = useTheme();

  return (
    <View style={styles.group}>
      <Text style={[styles.groupLabel, { color: colors.textSecondary }]}>Memory</Text>
      <View style={[styles.card, { backgroundColor: colors.cardBackground }]}>
        <View style={styles.row}>
          <View>
            <Text style={[styles.rowTitle, { color: colors.text }]}>Memory 管理</Text>
            <Text style={[styles.rowSubtitle, { color: colors.textSecondary }]}>Episodic / Semantic 配置将随后开放</Text>
          </View>
          <Text style={[styles.placeholder, { color: colors.textSecondary }]}>即将推出</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginBottom: 28 },
  groupLabel: {
    marginBottom: 8,
    paddingHorizontal: 4,
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  card: {
    borderRadius: 14,
    overflow: 'hidden',
  },
  row: {
    minHeight: 68,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  rowTitle: { fontSize: 17 },
  rowSubtitle: { marginTop: 4, fontSize: 13, lineHeight: 18 },
  placeholder: { fontSize: 13 },
});
