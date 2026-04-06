import { View, Text, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import { useTheme } from '../../theme/ThemeContext';
import { SettingToggleRow } from './SettingToggleRow';

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
        <SettingToggleRow
          label="跟随系统"
          value={isFollowSystem}
          onValueChange={handleFollowSystemChange}
          hasBorder={!isFollowSystem}
        />
        {!isFollowSystem && (
          <SettingToggleRow
            label="深色模式"
            value={isDarkManual}
            onValueChange={handleDarkModeChange}
          />
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
  footer: {
    paddingHorizontal: 4,
    paddingTop: 8,
    fontSize: 12,
  },
});
