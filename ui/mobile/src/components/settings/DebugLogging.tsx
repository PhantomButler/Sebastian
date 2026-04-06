import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Alert } from 'react-native';
import { getLogState, patchLogState } from '../../api/debug';
import { useSettingsStore } from '../../store/settings';
import { useTheme } from '../../theme/ThemeContext';
import { SettingToggleRow } from './SettingToggleRow';

export function DebugLogging() {
  const colors = useTheme();
  const { jwtToken } = useSettingsStore();
  const [llmStream, setLlmStream] = useState(false);
  const [sse, setSse] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!jwtToken) return;
    getLogState()
      .then((state) => {
        setLlmStream(state.llm_stream_enabled);
        setSse(state.sse_enabled);
      })
      .catch(() => {
        // 未登录或网络错误时静默忽略，保持默认值
      });
  }, [jwtToken]);

  async function toggle(field: 'llm_stream_enabled' | 'sse_enabled', value: boolean) {
    const prev = field === 'llm_stream_enabled' ? llmStream : sse;
    // 乐观更新
    if (field === 'llm_stream_enabled') setLlmStream(value);
    else setSse(value);

    setLoading(true);
    try {
      const updated = await patchLogState({ [field]: value });
      setLlmStream(updated.llm_stream_enabled);
      setSse(updated.sse_enabled);
    } catch {
      // 回滚
      if (field === 'llm_stream_enabled') setLlmStream(prev);
      else setSse(prev);
      Alert.alert('错误', '更新日志开关失败，请检查网络连接');
    } finally {
      setLoading(false);
    }
  }

  if (!jwtToken) return null;

  return (
    <View style={styles.group}>
      <Text style={[styles.groupLabel, { color: colors.textSecondary }]}>调试日志</Text>
      <View style={[styles.card, { backgroundColor: colors.cardBackground }]}>
        <SettingToggleRow
          label="LLM Stream 日志"
          value={llmStream}
          onValueChange={(v) => toggle('llm_stream_enabled', v)}
          disabled={loading}
          hasBorder
        />
        <SettingToggleRow
          label="SSE 事件日志"
          value={sse}
          onValueChange={(v) => toggle('sse_enabled', v)}
          disabled={loading}
        />
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
});
