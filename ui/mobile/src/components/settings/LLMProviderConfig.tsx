import { useState } from 'react';
import { View, Text, TextInput, Button, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import type { LLMProviderName } from '../../types';

const PROVIDERS: LLMProviderName[] = ['anthropic', 'openai'];

export function LLMProviderConfig() {
  const { llmProvider, setLlmProvider } = useSettingsStore();
  const [name, setName] = useState<LLMProviderName>(llmProvider?.name ?? 'anthropic');
  const [apiKey, setApiKey] = useState(llmProvider?.apiKey ?? '');

  async function handleSave() {
    await setLlmProvider({ name, apiKey: apiKey.trim() });
  }

  return (
    <View style={styles.section}>
      <Text style={styles.label}>LLM Provider</Text>
      <View style={styles.row}>
        {PROVIDERS.map((p) => (
          <Button key={p} title={p} onPress={() => setName(p)} color={name === p ? '#007AFF' : '#999'} />
        ))}
      </View>
      <TextInput
        style={styles.input}
        value={apiKey}
        onChangeText={setApiKey}
        placeholder="API Key"
        secureTextEntry
        autoCapitalize="none"
      />
      <Button title="保存" onPress={handleSave} />
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginBottom: 24 },
  label: { fontWeight: 'bold', marginBottom: 4 },
  row: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  input: { borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, marginBottom: 8 },
});
