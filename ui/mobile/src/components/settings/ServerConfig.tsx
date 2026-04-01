import { useState } from 'react';
import { View, Text, TextInput, Button, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import { checkHealth } from '../../api/auth';

export function ServerConfig() {
  const { serverUrl, setServerUrl } = useSettingsStore();
  const [input, setInput] = useState(serverUrl);
  const [status, setStatus] = useState<'idle' | 'ok' | 'fail'>('idle');

  async function handleSave() {
    await setServerUrl(input.trim());
    const ok = await checkHealth();
    setStatus(ok ? 'ok' : 'fail');
  }

  return (
    <View style={styles.section}>
      <Text style={styles.label}>Server URL</Text>
      <TextInput
        style={styles.input}
        value={input}
        onChangeText={setInput}
        placeholder="http://192.168.1.x:8000"
        autoCapitalize="none"
        keyboardType="url"
      />
      <Button title="保存并测试" onPress={handleSave} />
      {status === 'ok' && <Text style={styles.ok}>连接成功</Text>}
      {status === 'fail' && <Text style={styles.fail}>连接失败</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginBottom: 24 },
  label: { fontWeight: 'bold', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, marginBottom: 8 },
  ok: { color: 'green' },
  fail: { color: 'red' },
});
