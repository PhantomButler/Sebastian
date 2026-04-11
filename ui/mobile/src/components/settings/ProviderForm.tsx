import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from 'react';
import {
  Alert,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  ToastAndroid,
  TouchableOpacity,
  View,
} from 'react-native';
import { syncCurrentThinkingCapability } from '@/src/api/llm';
import { EyeCloseIcon, EyeOpenIcon } from '@/src/components/common/Icons';
import { useTheme } from '@/src/theme/ThemeContext';
import type {
  LLMProvider,
  LLMProviderCreate,
  LLMProviderType,
  ThinkingCapability,
} from '@/src/types';

const PROVIDER_TYPES: LLMProviderType[] = ['anthropic', 'openai'];

const CAPABILITY_OPTIONS: { value: ThinkingCapability | null; label: string; hint: string }[] = [
  { value: null, label: '未设置', hint: '后端不会注入思考相关参数' },
  { value: 'none', label: 'none', hint: '模型不支持思考控制' },
  { value: 'toggle', label: 'toggle', hint: '只支持开关，没有档位' },
  { value: 'effort', label: 'effort', hint: '支持 low / medium / high 三档' },
  { value: 'adaptive', label: 'adaptive', hint: 'Anthropic Adaptive，含 max 档位' },
  { value: 'always_on', label: 'always_on', hint: '模型固定思考，前端不再提供切换' },
];

const MODEL_PLACEHOLDERS: Record<LLMProviderType, string> = {
  anthropic: 'claude-opus-4-1 / claude-sonnet-4-5',
  openai: 'gpt-4o / o3 / o4-mini',
};

interface Props {
  initial?: LLMProvider;
  onSave: (data: LLMProviderCreate) => Promise<void>;
  onSubmittingChange?: (saving: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
}

export interface ProviderFormHandle {
  submit: () => Promise<void>;
}

interface SectionCardProps {
  title: string;
  description: string;
  children: React.ReactNode;
}

function SectionCard({ title, description, children }: SectionCardProps) {
  const colors = useTheme();

  return (
    <View style={[styles.card, { backgroundColor: colors.cardBackground }]}>
      <Text style={[styles.cardTitle, { color: colors.text }]}>{title}</Text>
      <Text style={[styles.cardDescription, { color: colors.textSecondary }]}>{description}</Text>
      <View style={styles.cardBody}>{children}</View>
    </View>
  );
}

export const ProviderForm = forwardRef<ProviderFormHandle, Props>(function ProviderForm(
  { initial, onSave, onSubmittingChange, onDirtyChange },
  ref,
) {
  const colors = useTheme();
  const [name, setName] = useState(initial?.name ?? '');
  const [providerType, setProviderType] = useState<LLMProviderType>(
    initial?.provider_type ?? 'anthropic',
  );
  const [apiKey, setApiKey] = useState(initial?.api_key ?? '');
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [model, setModel] = useState(initial?.model ?? '');
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '');
  const [isDefault, setIsDefault] = useState(initial?.is_default ?? false);
  const [thinkingCapability, setThinkingCapability] = useState<ThinkingCapability | null>(
    initial?.thinking_capability ?? null,
  );

  const isDirty = useMemo(
    () =>
      !initial ||
      name.trim() !== initial.name ||
      providerType !== initial.provider_type ||
      apiKey.trim() !== initial.api_key ||
      model.trim() !== initial.model ||
      baseUrl.trim() !== initial.base_url ||
      thinkingCapability !== initial.thinking_capability ||
      isDefault !== initial.is_default,
    [initial, name, providerType, apiKey, model, baseUrl, thinkingCapability, isDefault],
  );

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  function notifyClamped(from: string, to: string) {
    const msg = `${from} 在新模型下不可用，已切换为 ${to}`;
    if (Platform.OS === 'android') {
      ToastAndroid.show(msg, ToastAndroid.SHORT);
    } else {
      Alert.alert('思考档位已调整', msg);
    }
  }

  async function submit() {
    if (!name.trim() || !apiKey.trim() || !model.trim() || !baseUrl.trim()) {
      Alert.alert('错误', '请填写名称、API Key、模型和 Base URL');
      return;
    }

    if (!isDirty) {
      return;
    }

    onSubmittingChange?.(true);
    try {
      await onSave({
        name: name.trim(),
        provider_type: providerType,
        api_key: apiKey.trim(),
        model: model.trim(),
        base_url: baseUrl.trim(),
        thinking_capability: thinkingCapability,
        is_default: isDefault,
      });
      await syncCurrentThinkingCapability((report) => notifyClamped(report.from, report.to));
    } finally {
      onSubmittingChange?.(false);
    }
  }

  useImperativeHandle(
    ref,
    () => ({
      submit,
    }),
    [submit],
  );

  return (
    <View style={styles.form}>
      <SectionCard title="基础信息" description="先定义这条 Provider 配置的名字和服务类型。">
        <Text style={[styles.label, { color: colors.textSecondary }]}>名称</Text>
        <TextInput
          style={[
            styles.input,
            styles.elevatedInput,
            {
              backgroundColor: colors.secondaryBackground,
              borderColor: colors.border,
              color: colors.text,
            },
          ]}
          value={name}
          onChangeText={setName}
          placeholder="Claude / OpenAI / DeepSeek..."
          placeholderTextColor={colors.textSecondary}
        />

        <Text style={[styles.label, { color: colors.textSecondary }]}>Provider 类型</Text>
        <View style={[styles.segmented, { backgroundColor: colors.segmentedBg }]}>
          {PROVIDER_TYPES.map((type) => {
            const active = providerType === type;
            return (
              <TouchableOpacity
                key={type}
                style={[
                  styles.segment,
                  active && [styles.segmentActive, { backgroundColor: colors.cardBackground }],
                ]}
                onPress={() => {
                  setProviderType(type);
                }}
                activeOpacity={0.8}
              >
                <Text
                  style={[
                    styles.segmentText,
                    { color: colors.textSecondary },
                    active && { color: colors.text },
                  ]}
                >
                  {type}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>
      </SectionCard>

      <SectionCard title="连接配置" description="填写鉴权信息和服务接入地址。">
        <Text style={[styles.label, { color: colors.textSecondary }]}>API Key</Text>
        <View
          style={[
            styles.inputShell,
            {
              backgroundColor: colors.secondaryBackground,
              borderColor: colors.border,
            },
          ]}
        >
          <TextInput
            style={[styles.input, styles.inputWithAccessory, { color: colors.text }]}
            value={apiKey}
            onChangeText={setApiKey}
            placeholder="sk-..."
            placeholderTextColor={colors.textSecondary}
            secureTextEntry={!apiKeyVisible}
            autoCapitalize="none"
          />
          <TouchableOpacity
            style={styles.inputAccessory}
            onPress={() => setApiKeyVisible((value) => !value)}
            hitSlop={8}
            activeOpacity={0.7}
          >
            {apiKeyVisible ? (
              <EyeOpenIcon size={18} color={colors.textSecondary} />
            ) : (
              <EyeCloseIcon size={18} color={colors.textSecondary} />
            )}
          </TouchableOpacity>
        </View>

        <Text style={[styles.label, { color: colors.textSecondary }]}>Base URL</Text>
        <TextInput
          style={[
            styles.input,
            styles.elevatedInput,
            {
              backgroundColor: colors.secondaryBackground,
              borderColor: colors.border,
              color: colors.text,
            },
          ]}
          value={baseUrl}
          onChangeText={setBaseUrl}
          placeholder="https://api.example.com/v1"
          placeholderTextColor={colors.textSecondary}
          autoCapitalize="none"
        />
      </SectionCard>

      <SectionCard title="模型与能力" description="设置默认模型，以及这类模型支持的思考控制能力。">
        <Text style={[styles.label, { color: colors.textSecondary }]}>模型</Text>
        <TextInput
          style={[
            styles.input,
            styles.elevatedInput,
            {
              backgroundColor: colors.secondaryBackground,
              borderColor: colors.border,
              color: colors.text,
            },
          ]}
          value={model}
          onChangeText={setModel}
          autoCapitalize="none"
          placeholder={MODEL_PLACEHOLDERS[providerType]}
          placeholderTextColor={colors.textSecondary}
        />

        <Text style={[styles.label, { color: colors.textSecondary }]}>
          思考能力（thinking_capability）
        </Text>
        <View style={styles.capabilityList}>
          {CAPABILITY_OPTIONS.map((option) => {
            const active = thinkingCapability === option.value;
            return (
              <TouchableOpacity
                key={option.label}
                style={[
                  styles.capabilityRow,
                  {
                    backgroundColor: active ? colors.activeSessionBg : colors.inputBackground,
                    borderColor: active ? colors.accent : 'transparent',
                  },
                ]}
                onPress={() => setThinkingCapability(option.value)}
                activeOpacity={0.7}
              >
                <View style={styles.capabilityBody}>
                  <Text style={[styles.capabilityLabel, { color: active ? colors.accent : colors.text }]}>
                    {option.label}
                  </Text>
                  <Text style={[styles.capabilityHint, { color: colors.textSecondary }]}>
                    {option.hint}
                  </Text>
                </View>
                {active ? <Text style={[styles.capabilityCheck, { color: colors.accent }]}>已选</Text> : null}
              </TouchableOpacity>
            );
          })}
        </View>
      </SectionCard>

      <SectionCard
        title="默认设置"
        description="默认 Provider 是全局单选项，切换后会自动取消其他 Provider 的默认状态。"
      >
        <TouchableOpacity
          style={[
            styles.defaultRow,
            {
              backgroundColor: colors.inputBackground,
              borderColor: isDefault ? colors.accent : colors.segmentedBg,
            },
          ]}
          onPress={() => setIsDefault((value) => !value)}
          activeOpacity={0.8}
        >
          <View style={styles.defaultBody}>
            <Text style={[styles.defaultTitle, { color: colors.text }]}>设为当前默认 Provider</Text>
            <Text style={[styles.defaultHint, { color: colors.textSecondary }]}>
              {isDefault
                ? '保存后 Sebastian 会优先使用它，其他默认项会自动取消。'
                : '不设为默认时，这条 Provider 只作为可选配置保留。'}
            </Text>
          </View>
          <View
            style={[
              styles.defaultBadge,
              { backgroundColor: isDefault ? colors.accent : colors.segmentedBg },
            ]}
          >
            <Text
              style={[
                styles.defaultBadgeText,
                { color: isDefault ? '#FFFFFF' : colors.textSecondary },
              ]}
            >
              {isDefault ? '已选中' : '未选中'}
            </Text>
          </View>
        </TouchableOpacity>
      </SectionCard>
    </View>
  );
});

const styles = StyleSheet.create({
  form: {
    gap: 14,
    paddingBottom: 8,
  },
  card: {
    borderRadius: 18,
    padding: 18,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: '600',
  },
  cardDescription: {
    marginTop: 6,
    fontSize: 13,
    lineHeight: 18,
  },
  cardBody: {
    marginTop: 16,
  },
  label: {
    fontSize: 13,
    marginBottom: 8,
    marginTop: 14,
  },
  input: {
    minHeight: 48,
    borderRadius: 14,
    paddingHorizontal: 14,
    fontSize: 17,
  },
  inputShell: {
    minHeight: 48,
    borderRadius: 14,
    borderWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
  },
  inputWithAccessory: {
    flex: 1,
    borderWidth: 0,
    backgroundColor: 'transparent',
    paddingRight: 4,
  },
  inputAccessory: {
    width: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  elevatedInput: {
    borderWidth: 1,
  },
  segmented: {
    flexDirection: 'row',
    padding: 4,
    borderRadius: 14,
    marginTop: 2,
  },
  segment: {
    flex: 1,
    minHeight: 40,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  segmentActive: {},
  segmentText: {
    fontSize: 15,
    fontWeight: '600',
  },
  capabilityList: {
    gap: 8,
    marginTop: 2,
  },
  capabilityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 14,
    borderWidth: 1,
  },
  capabilityBody: {
    flex: 1,
  },
  capabilityLabel: {
    fontSize: 15,
    fontWeight: '600',
  },
  capabilityHint: {
    fontSize: 12,
    marginTop: 3,
    lineHeight: 17,
  },
  capabilityCheck: {
    fontSize: 13,
    fontWeight: '700',
  },
  defaultRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 14,
    paddingHorizontal: 14,
  },
  defaultBody: {
    flex: 1,
    paddingRight: 12,
  },
  defaultTitle: {
    fontSize: 16,
    fontWeight: '600',
  },
  defaultHint: {
    marginTop: 4,
    fontSize: 13,
    lineHeight: 18,
  },
  defaultBadge: {
    minWidth: 70,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    alignItems: 'center',
  },
  defaultBadgeText: {
    fontSize: 12,
    fontWeight: '700',
  },
});
