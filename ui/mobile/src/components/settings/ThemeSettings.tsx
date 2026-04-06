import { View, Text, Switch, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import { useTheme } from '../../theme/ThemeContext';

export function ThemeSettings() {
  const { themeMode, setThemeMode } = useSettingsStore();
  const colors = useTheme();

  const isFollowSystem = themeMode === 'system';
  const isDarkManual = themeMode === 'dark';

  function handleFollowSystemChange(value: boolean) {
    if (value) {
      setThemeMode('system');
    } else {
      // 关闭跟随系统时，默认切到 light
      setThemeMode('light');
    }
  }

  function handleDarkModeChange(value: boolean) {
    setThemeMode(value ? 'dark' : 'light');
  }

  return (
    <View style={styles.group}>
      <Text style={[styles.groupLabel, { color: colors.textSecondary }]}>外观</Text>
      <View style={[styles.card, { backgroundColor: colors.cardBackground }]}>
        <View style={[styles.row, !isFollowSystem && styles.rowBorder, { borderBottomColor: colors.border }]}>
          <Text style={[styles.rowTitle, { color: colors.text }]}>跟随系统</Text>
          <Switch
            value={isFollowSystem}
            onValueChange={handleFollowSystemChange}
          />
        </View>
        {!isFollowSystem && (
          <View style={styles.row}>
            <Text style={[styles.rowTitle, { color: colors.text }]}>深色模式</Text>
            <Switch
              value={isDarkManual}
              onValueChange={handleDarkModeChange}
            />
          </View>
        )}
      </View>
      <Text style={[styles.footer, { color: colors.textSecondary }]}>
        {isFollowSystem
          ? '开启后，外观将自动跟随系统设置切换'
          : '关闭跟随系统后，可手动选择日间或深色模式'}
      </Text>
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
    minHeight: 52,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  rowBorder: {
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  rowTitle: { fontSize: 17 },
  footer: {
    paddingHorizontal: 4,
    paddingTop: 8,
    fontSize: 12,
  },
});
