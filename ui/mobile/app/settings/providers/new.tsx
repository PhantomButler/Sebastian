import { useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import {
  ProviderForm,
  type ProviderFormHandle,
} from '@/src/components/settings/ProviderForm';
import { ProviderEditorLayout } from '@/src/components/settings/ProviderEditorLayout';
import { useLLMProvidersStore } from '@/src/store/llmProviders';
import { useSettingsStore } from '@/src/store/settings';
import { useTheme } from '@/src/theme/ThemeContext';
import type { LLMProviderCreate } from '@/src/types';

export default function NewProviderScreen() {
  const router = useRouter();
  const colors = useTheme();
  const jwtToken = useSettingsStore((state) => state.jwtToken);
  const create = useLLMProvidersStore((state) => state.create);
  const formRef = useRef<ProviderFormHandle>(null);
  const [saving, setSaving] = useState(false);

  async function handleSave(data: LLMProviderCreate) {
    await create(data);
  }

  async function handleDone() {
    await formRef.current?.submit();
    router.back();
  }

  return (
    <ProviderEditorLayout
      title="添加 Provider"
      subtitle="新增一个可用模型提供商，并决定是否设为默认。"
      onDone={jwtToken ? () => void handleDone() : undefined}
      doneDisabled={saving}
      doneLoading={saving}
    >
      {jwtToken ? (
        <ProviderForm ref={formRef} onSave={handleSave} onSubmittingChange={setSaving} />
      ) : (
        <View style={[styles.feedbackCard, { backgroundColor: colors.cardBackground }]}>
          <Text style={[styles.feedbackTitle, { color: colors.text }]}>请先登录</Text>
          <Text style={[styles.feedbackText, { color: colors.textSecondary }]}>
            登录 Owner 账户后，才能新增 Provider。
          </Text>
        </View>
      )}
    </ProviderEditorLayout>
  );
}

const styles = StyleSheet.create({
  feedbackCard: {
    borderRadius: 14,
    padding: 18,
  },
  feedbackTitle: {
    fontSize: 17,
    fontWeight: '600',
  },
  feedbackText: {
    marginTop: 8,
    fontSize: 14,
    lineHeight: 20,
  },
});
