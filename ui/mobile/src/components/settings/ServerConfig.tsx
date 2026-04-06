import { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import { checkHealth } from '../../api/auth';
import { useTheme } from '../../theme/ThemeContext';

export function ServerConfig() {
  const colors = useTheme();
  const { serverUrl, setServerUrl } = useSettingsStore();
  const [input, setInput] = useState(serverUrl);
  const [status, setStatus] = useState<'idle' | 'ok' | 'fail'>('idle');

  async function handleSave() {
    await setServerUrl(input.trim());
    const ok = await checkHealth();
    setStatus(ok ? 'ok' : 'fail');
  }

  return (
    <View style={styles.group}>
      <Text style={[styles.groupLabel, { color: colors.textSecondary }]}>连接</Text>
      <View style={[styles.card, { backgroundColor: colors.cardBackground }]}>
        <View style={[styles.row, { borderBottomColor: colors.border }]}>
          <Text style={[styles.rowTitle, { color: colors.text }]}>Server URL</Text>
          <Text
            style={[
              styles.statusText,
              status === 'ok' && { color: colors.success, fontWeight: '600' },
              status === 'fail' && { color: colors.error, fontWeight: '600' },
              status === 'idle' && { color: colors.textSecondary },
            ]}
          >
            {status === 'ok' ? '已连接' : status === 'fail' ? '失败' : '未测试'}
          </Text>
        </View>
        <View style={styles.inputBlock}>
          <TextInput
            style={[styles.input, { backgroundColor: colors.inputBackground, color: colors.text }]}
            value={input}
            onChangeText={setInput}
            placeholder="http://192.168.1.x:8000"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            keyboardType="url"
          />
        </View>
        <TouchableOpacity style={[styles.button, { backgroundColor: colors.accent }]} onPress={handleSave}>
          <Text style={styles.buttonText}>保存并测试</Text>
        </TouchableOpacity>
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
    minHeight: 52,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  rowTitle: { fontSize: 17 },
  statusText: { fontSize: 15 },
  inputBlock: { padding: 16, paddingBottom: 12 },
  input: {
    minHeight: 46,
    borderRadius: 12,
    paddingHorizontal: 14,
    fontSize: 17,
  },
  button: {
    marginHorizontal: 16,
    marginBottom: 16,
    minHeight: 46,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonText: { fontSize: 17, fontWeight: '600', color: '#FFFFFF' },
});
