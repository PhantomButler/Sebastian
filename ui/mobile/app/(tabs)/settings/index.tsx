import { useState } from 'react';
import { ScrollView, View, Text, TextInput, Button, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../../src/store/settings';
import { login, logout } from '../../../src/api/auth';
import { ServerConfig } from '../../../src/components/settings/ServerConfig';
import { LLMProviderConfig } from '../../../src/components/settings/LLMProviderConfig';
import { MemorySection } from '../../../src/components/settings/MemorySection';

export default function SettingsScreen() {
  const { jwtToken, setJwtToken } = useSettingsStore();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function handleLogin() {
    try {
      const token = await login(password);
      await setJwtToken(token);
      setPassword('');
      setError('');
    } catch {
      setError('登录失败，请检查密码');
    }
  }

  async function handleLogout() {
    try { await logout(); } catch { /* ignore */ }
    await setJwtToken(null);
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <ServerConfig />
      {jwtToken ? (
        <View style={styles.section}>
          <Text style={styles.label}>已登录</Text>
          <Button title="退出登录" onPress={handleLogout} color="red" />
        </View>
      ) : (
        <View style={styles.section}>
          <Text style={styles.label}>登录</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="密码"
            secureTextEntry
          />
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Button title="登录" onPress={handleLogin} />
        </View>
      )}
      <LLMProviderConfig />
      <MemorySection />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16 },
  section: { marginBottom: 24 },
  label: { fontWeight: 'bold', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, marginBottom: 8 },
  error: { color: 'red', marginBottom: 8 },
});
