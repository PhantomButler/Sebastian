import { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet } from 'react-native';
import { useSettingsStore } from '../../store/settings';
import type { LLMProviderType } from '../../types';

const PROVIDERS: LLMProviderType[] = ['anthropic', 'openai'];

export function LLMProviderConfig() {
  const { llmProvider, setLlmProvider } = useSettingsStore();
  const [providerType, setProviderType] = useState<LLMProviderType>(
    llmProvider?.providerType ?? 'anthropic',
  );
  const [apiKey, setApiKey] = useState(llmProvider?.apiKey ?? '');

  async function handleSave() {
    await setLlmProvider({ providerType, apiKey: apiKey.trim() });
  }

  return (
    <View style={styles.group}>
      <Text style={styles.groupLabel}>模型</Text>
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.rowTitle}>LLM Provider</Text>
          <Text style={styles.rowValue}>{providerType}</Text>
        </View>
        <View style={styles.segmented}>
          {PROVIDERS.map((provider) => (
            <TouchableOpacity
              key={provider}
              style={[
                styles.segment,
                providerType === provider && styles.segmentActive,
              ]}
              onPress={() => setProviderType(provider)}
            >
              <Text
                style={[
                  styles.segmentText,
                  providerType === provider && styles.segmentTextActive,
                ]}
              >
                {provider}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
        <View style={styles.inputBlock}>
          <Text style={styles.inputLabel}>API Key</Text>
          <TextInput
            style={styles.input}
            value={apiKey}
            onChangeText={setApiKey}
            placeholder="输入 API Key"
            placeholderTextColor="#A0A0A5"
            secureTextEntry
            autoCapitalize="none"
          />
        </View>
        <TouchableOpacity style={styles.button} onPress={handleSave}>
          <Text style={styles.buttonText}>保存</Text>
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
    color: '#6D6D72',
    textTransform: 'uppercase',
  },
  card: {
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
    overflow: 'hidden',
  },
  row: {
    minHeight: 52,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#D1D1D6',
  },
  rowTitle: { fontSize: 17, color: '#111111' },
  rowValue: { fontSize: 15, color: '#8E8E93' },
  segmented: {
    flexDirection: 'row',
    margin: 16,
    marginBottom: 12,
    padding: 4,
    borderRadius: 12,
    backgroundColor: '#F2F2F7',
  },
  segment: {
    flex: 1,
    minHeight: 36,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  segmentActive: { backgroundColor: '#FFFFFF' },
  segmentText: { fontSize: 15, color: '#6D6D72', fontWeight: '500' },
  segmentTextActive: { color: '#111111' },
  inputBlock: { paddingHorizontal: 16, paddingBottom: 12 },
  inputLabel: { marginBottom: 8, fontSize: 13, color: '#6D6D72' },
  input: {
    minHeight: 46,
    borderRadius: 12,
    backgroundColor: '#F2F2F7',
    paddingHorizontal: 14,
    fontSize: 17,
    color: '#111111',
  },
  button: {
    marginHorizontal: 16,
    marginBottom: 16,
    minHeight: 46,
    borderRadius: 12,
    backgroundColor: '#007AFF',
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonText: { fontSize: 17, fontWeight: '600', color: '#FFFFFF' },
});
