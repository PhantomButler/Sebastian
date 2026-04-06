import { useState } from 'react';
import {
  ScrollView, View, Text, TextInput,
  TouchableOpacity, StyleSheet,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSettingsStore } from '@/src/store/settings';
import { login, logout } from '@/src/api/auth';
import { ServerConfig } from '@/src/components/settings/ServerConfig';
import { LLMProviderConfig } from '@/src/components/settings/LLMProviderConfig';
import { MemorySection } from '@/src/components/settings/MemorySection';
import { DebugLogging } from '@/src/components/settings/DebugLogging';

export default function SettingsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
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
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.container,
        { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 32 },
      ]}
    >
      <TouchableOpacity style={styles.backBtn} onPress={() => router.back()}>
        <Text style={styles.backText}>‹ 返回</Text>
      </TouchableOpacity>

      <View style={styles.hero}>
        <Text style={styles.heroTitle}>设置</Text>
        <Text style={styles.heroSubtitle}>
          配置 Sebastian 的连接、登录状态和模型提供商。
        </Text>
      </View>

      <ServerConfig />
      {jwtToken ? (
        <View style={styles.group}>
          <Text style={styles.groupLabel}>账户</Text>
          <View style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.rowTitle}>Owner 登录</Text>
              <Text style={styles.statusOk}>已连接</Text>
            </View>
            <TouchableOpacity style={styles.destructiveButton} onPress={handleLogout}>
              <Text style={styles.destructiveButtonText}>退出登录</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : (
        <View style={styles.group}>
          <Text style={styles.groupLabel}>账户</Text>
          <View style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.rowTitle}>Owner 登录</Text>
              <Text style={styles.statusIdle}>未登录</Text>
            </View>
            <View style={styles.inputBlock}>
              <Text style={styles.inputLabel}>密码</Text>
              <TextInput
                style={styles.input}
                value={password}
                onChangeText={setPassword}
                placeholder="输入 Owner 密码"
                placeholderTextColor="#A0A0A5"
                secureTextEntry
              />
            </View>
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <TouchableOpacity style={styles.primaryButton} onPress={handleLogin}>
              <Text style={styles.primaryButtonText}>登录</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}
      <LLMProviderConfig />
      <MemorySection />
      <DebugLogging />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen:                { flex: 1, backgroundColor: '#F2F2F7' },
  container:             { paddingHorizontal: 16 },
  backBtn:               { marginBottom: 8 },
  backText:              { fontSize: 16, color: '#007AFF' },
  hero:                  { marginBottom: 18, paddingHorizontal: 4 },
  heroTitle:             { fontSize: 34, fontWeight: '700', color: '#000000' },
  heroSubtitle:          { marginTop: 6, fontSize: 15, lineHeight: 21, color: '#6D6D72' },
  group:                 { marginBottom: 28 },
  groupLabel:            { marginBottom: 8, paddingHorizontal: 4, fontSize: 13, fontWeight: '600', color: '#6D6D72', textTransform: 'uppercase' },
  card:                  { borderRadius: 14, backgroundColor: '#FFFFFF', overflow: 'hidden' },
  row:                   { minHeight: 52, paddingHorizontal: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#D1D1D6' },
  rowTitle:              { fontSize: 17, color: '#111111' },
  statusOk:              { fontSize: 15, color: '#34C759', fontWeight: '600' },
  statusIdle:            { fontSize: 15, color: '#8E8E93' },
  inputBlock:            { paddingHorizontal: 16, paddingTop: 14, paddingBottom: 10 },
  inputLabel:            { marginBottom: 8, fontSize: 13, color: '#6D6D72' },
  input:                 { minHeight: 46, borderRadius: 12, backgroundColor: '#F2F2F7', paddingHorizontal: 14, fontSize: 17, color: '#111111' },
  error:                 { paddingHorizontal: 16, paddingBottom: 10, fontSize: 13, color: '#FF3B30' },
  primaryButton:         { marginHorizontal: 16, marginBottom: 16, minHeight: 46, borderRadius: 12, backgroundColor: '#007AFF', alignItems: 'center', justifyContent: 'center' },
  primaryButtonText:     { fontSize: 17, fontWeight: '600', color: '#FFFFFF' },
  destructiveButton:     { margin: 16, minHeight: 46, borderRadius: 12, backgroundColor: '#FFF2F1', alignItems: 'center', justifyContent: 'center' },
  destructiveButtonText: { fontSize: 17, fontWeight: '600', color: '#FF3B30' },
});
