import { useEffect, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  StyleSheet,
} from 'react-native';
import { useLLMProvidersStore } from '../../store/llmProviders';
import { useSettingsStore } from '../../store/settings';
import { syncCurrentThinkingCapability } from '../../api/llm';
import type {
  LLMProvider,
  LLMProviderCreate,
  LLMProviderType,
  ThinkingCapability,
} from '../../types';
import { useTheme } from '../../theme/ThemeContext';

const PROVIDER_TYPES: LLMProviderType[] = ['anthropic', 'openai'];

const CAPABILITY_OPTIONS: { value: ThinkingCapability | null; label: string; hint: string }[] = [
  { value: null, label: '未设置', hint: '后端不会注入思考相关参数' },
  { value: 'none', label: 'none', hint: '模型不支持思考控制' },
  { value: 'toggle', label: 'toggle', hint: '只支持开/关，无档位' },
  { value: 'effort', label: 'effort', hint: '支持 low/medium/high 三档' },
  { value: 'adaptive', label: 'adaptive', hint: 'Anthropic Adaptive（含 max）' },
  { value: 'always_on', label: 'always_on', hint: '模型必然思考，UI 固定' },
];

const DEFAULT_MODELS: Record<LLMProviderType, string> = {
  anthropic: 'claude-opus-4-6',
  openai: 'gpt-4o',
};

function ProviderForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: LLMProvider;
  onSave: (data: LLMProviderCreate) => Promise<void>;
  onCancel: () => void;
}) {
  const colors = useTheme();
  const [name, setName] = useState(initial?.name ?? '');
  const [providerType, setProviderType] = useState<LLMProviderType>(
    initial?.provider_type ?? 'anthropic',
  );
  const [apiKey, setApiKey] = useState(initial?.api_key ?? '');
  const [model, setModel] = useState(initial?.model ?? DEFAULT_MODELS.anthropic);
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '');
  const [isDefault, setIsDefault] = useState(initial?.is_default ?? false);
  const [thinkingCapability, setThinkingCapability] = useState<ThinkingCapability | null>(
    initial?.thinking_capability ?? null,
  );
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!name.trim() || !apiKey.trim() || !model.trim()) {
      Alert.alert('错误', '请填写名称、API Key 和模型');
      return;
    }
    setSaving(true);
    try {
      await onSave({
        name: name.trim(),
        provider_type: providerType,
        api_key: apiKey.trim(),
        model: model.trim(),
        base_url: baseUrl.trim() || null,
        thinking_capability: thinkingCapability,
        is_default: isDefault,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <View style={[styles.form, { backgroundColor: colors.cardBackground }]}>
      <Text style={[styles.label, { color: colors.textSecondary }]}>名称</Text>
      <TextInput
        style={[styles.input, { backgroundColor: colors.inputBackground, color: colors.text }]}
        value={name}
        onChangeText={setName}
        placeholder="如：Claude 家用"
        placeholderTextColor={colors.textMuted}
      />

      <Text style={[styles.label, { color: colors.textSecondary }]}>Provider 类型</Text>
      <View style={[styles.segmented, { backgroundColor: colors.segmentedBg }]}>
        {PROVIDER_TYPES.map((pt) => (
          <TouchableOpacity
            key={pt}
            style={[styles.segment, providerType === pt && [styles.segmentActive, { backgroundColor: colors.cardBackground }]]}
            onPress={() => {
              setProviderType(pt);
              setModel(DEFAULT_MODELS[pt]);
            }}
          >
            <Text style={[styles.segmentText, { color: colors.textSecondary }, providerType === pt && { color: colors.text }]}>
              {pt}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <Text style={[styles.label, { color: colors.textSecondary }]}>API Key</Text>
      <TextInput
        style={[styles.input, { backgroundColor: colors.inputBackground, color: colors.text }]}
        value={apiKey}
        onChangeText={setApiKey}
        placeholder="sk-ant-... 或 sk-..."
        placeholderTextColor={colors.textMuted}
        secureTextEntry
        autoCapitalize="none"
      />

      <Text style={[styles.label, { color: colors.textSecondary }]}>模型</Text>
      <TextInput
        style={[styles.input, { backgroundColor: colors.inputBackground, color: colors.text }]}
        value={model}
        onChangeText={setModel}
        autoCapitalize="none"
        placeholderTextColor={colors.textMuted}
      />

      <Text style={[styles.label, { color: colors.textSecondary }]}>Base URL（可选，留空用默认）</Text>
      <TextInput
        style={[styles.input, { backgroundColor: colors.inputBackground, color: colors.text }]}
        value={baseUrl}
        onChangeText={setBaseUrl}
        placeholder="https://api.example.com/v1"
        placeholderTextColor={colors.textMuted}
        autoCapitalize="none"
      />

      <TouchableOpacity
        style={styles.toggleRow}
        onPress={() => setIsDefault((v) => !v)}
      >
        <Text style={[styles.toggleLabel, { color: colors.text }]}>设为默认 Provider</Text>
        <Text style={[styles.toggleValue, { color: colors.accent }]}>{isDefault ? '✓' : '○'}</Text>
      </TouchableOpacity>

      <Text style={[styles.label, { color: colors.textSecondary }]}>思考能力（thinking_capability）</Text>
      <View style={styles.capabilityList}>
        {CAPABILITY_OPTIONS.map((opt) => {
          const active = thinkingCapability === opt.value;
          return (
            <TouchableOpacity
              key={opt.label}
              style={[
                styles.capabilityRow,
                {
                  backgroundColor: active ? colors.activeSessionBg : colors.inputBackground,
                  borderColor: active ? colors.accent : 'transparent',
                },
              ]}
              onPress={() => setThinkingCapability(opt.value)}
              activeOpacity={0.7}
            >
              <View style={{ flex: 1 }}>
                <Text style={[styles.capabilityLabel, { color: active ? colors.accent : colors.text }]}>
                  {opt.label}
                </Text>
                <Text style={[styles.capabilityHint, { color: colors.textSecondary }]}>
                  {opt.hint}
                </Text>
              </View>
              {active && <Text style={{ color: colors.accent, fontSize: 16 }}>✓</Text>}
            </TouchableOpacity>
          );
        })}
      </View>

      <View style={styles.buttonRow}>
        <TouchableOpacity style={[styles.btn, styles.btnCancel, { backgroundColor: colors.inputBackground }]} onPress={onCancel}>
          <Text style={[styles.btnCancelText, { color: colors.text }]}>取消</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.btn, { backgroundColor: colors.accent }]} onPress={handleSave} disabled={saving}>
          {saving ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.btnSaveText}>保存</Text>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
}

export function LLMProviderConfig() {
  const colors = useTheme();
  const { providers, loading, error, fetch, create, update, remove } = useLLMProvidersStore();
  const { jwtToken } = useSettingsStore();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<LLMProvider | null>(null);

  useEffect(() => {
    if (jwtToken) fetch();
  }, [jwtToken]);

  async function handleCreate(data: LLMProviderCreate) {
    await create(data);
    await syncCurrentThinkingCapability();
    setShowForm(false);
  }

  async function handleUpdate(data: LLMProviderCreate) {
    if (!editing) return;
    await update(editing.id, data);
    await syncCurrentThinkingCapability();
    setEditing(null);
  }

  async function handleDelete(provider: LLMProvider) {
    Alert.alert('删除 Provider', `确认删除 "${provider.name}"？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: async () => {
          await remove(provider.id);
        },
      },
    ]);
  }

  if (showForm || editing) {
    return (
      <View style={styles.group}>
        <Text style={[styles.groupLabel, { color: colors.textSecondary }]}>模型</Text>
        <ProviderForm
          initial={editing ?? undefined}
          onSave={editing ? handleUpdate : handleCreate}
          onCancel={() => {
            setShowForm(false);
            setEditing(null);
          }}
        />
      </View>
    );
  }

  return (
    <View style={styles.group}>
      <Text style={[styles.groupLabel, { color: colors.textSecondary }]}>模型</Text>

      {loading && <ActivityIndicator style={{ marginBottom: 12 }} />}
      {error && <Text style={[styles.errorText, { color: colors.error }]}>{error}</Text>}

      {providers.map((p) => (
        <View key={p.id} style={[styles.card, { backgroundColor: colors.cardBackground }]}>
          <View style={styles.cardRow}>
            <View style={{ flex: 1 }}>
              <Text style={[styles.cardTitle, { color: colors.text }]}>
                {p.name}
                {p.is_default ? ' ★' : ''}
              </Text>
              <Text style={[styles.cardSub, { color: colors.textSecondary }]}>
                {p.provider_type} · {p.model}
              </Text>
            </View>
            <View style={styles.cardActions}>
              <TouchableOpacity onPress={() => setEditing(p)} style={styles.actionBtn}>
                <Text style={[styles.actionBtnText, { color: colors.accent }]}>编辑</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => handleDelete(p)} style={styles.actionBtn}>
                <Text style={[styles.actionBtnText, { color: colors.error }]}>删除</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      ))}

      <TouchableOpacity style={[styles.addBtn, { backgroundColor: colors.cardBackground }]} onPress={() => setShowForm(true)}>
        <Text style={[styles.addBtnText, { color: colors.accent }]}>+ 添加 Provider</Text>
      </TouchableOpacity>
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
    marginBottom: 8,
    overflow: 'hidden',
  },
  cardRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  cardTitle: { fontSize: 17, fontWeight: '500' },
  cardSub: { fontSize: 13, marginTop: 2 },
  cardActions: { flexDirection: 'row', gap: 12 },
  actionBtn: { padding: 4 },
  actionBtnText: { fontSize: 15 },
  addBtn: {
    borderRadius: 14,
    minHeight: 48,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addBtnText: { fontSize: 17 },
  form: {
    borderRadius: 14,
    padding: 16,
  },
  label: { fontSize: 13, marginBottom: 6, marginTop: 12 },
  input: {
    minHeight: 46,
    borderRadius: 12,
    paddingHorizontal: 14,
    fontSize: 17,
  },
  segmented: {
    flexDirection: 'row',
    padding: 4,
    borderRadius: 12,
  },
  segment: { flex: 1, minHeight: 36, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  segmentActive: {},
  segmentText: { fontSize: 15, fontWeight: '500' },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 16,
    paddingVertical: 4,
  },
  toggleLabel: { fontSize: 17 },
  toggleValue: { fontSize: 20 },
  capabilityList: { gap: 8 },
  capabilityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 10,
    borderWidth: 1,
  },
  capabilityLabel: { fontSize: 15, fontWeight: '500' },
  capabilityHint: { fontSize: 12, marginTop: 2 },
  buttonRow: { flexDirection: 'row', gap: 12, marginTop: 20 },
  btn: { flex: 1, minHeight: 46, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  btnCancel: {},
  btnCancelText: { fontSize: 17 },
  btnSaveText: { fontSize: 17, fontWeight: '600', color: '#FFFFFF' },
  errorText: { fontSize: 15, marginBottom: 8 },
});
