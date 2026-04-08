import { useState } from 'react';
import { TouchableOpacity, Text, StyleSheet, View } from 'react-native';
import { ThinkIcon } from '../common/Icons';
import { useTheme } from '../../theme/ThemeContext';
import { EffortPicker } from './EffortPicker';
import { useSettingsStore } from '../../store/settings';
import { EFFORT_LEVELS_BY_CAPABILITY } from '../../types';
import type { ThinkingEffort } from '../../types';

interface Props {
  current: ThinkingEffort;
  onChange: (next: ThinkingEffort) => void;
}

const ACTIVE_BG = '#E8F0FE';
const ACTIVE_FG = '#3B82F6';

const SHORT_LABEL: Record<ThinkingEffort, string> = {
  off: '思考',
  on: '思考',
  low: '思考·低',
  medium: '思考·中',
  high: '思考·高',
  max: '思考·最大',
};

export function ThinkButton({ current, onChange }: Props) {
  const colors = useTheme();
  const capability = useSettingsStore((s) => s.currentThinkingCapability);
  const [pickerVisible, setPickerVisible] = useState(false);

  // Not loaded / not configured: disabled pill
  if (capability === null) {
    return (
      <View style={[styles.pill, { backgroundColor: colors.inputBackground, opacity: 0.5 }]}>
        <ThinkIcon size={16} color={colors.textMuted} />
        <Text style={[styles.label, { color: colors.textMuted }]}>思考</Text>
      </View>
    );
  }

  // Not supported: hide entirely
  if (capability === 'none') {
    return null;
  }

  // Always-on: non-interactive badge
  if (capability === 'always_on') {
    return (
      <View style={[styles.pill, { backgroundColor: colors.inputBackground }]}>
        <ThinkIcon size={16} color={colors.textMuted} />
        <Text style={[styles.label, { color: colors.textMuted }]}>思考·自动</Text>
      </View>
    );
  }

  // Toggle: single-tap on/off, no picker
  if (capability === 'toggle') {
    const active = current === 'on';
    return (
      <TouchableOpacity
        style={[styles.pill, { backgroundColor: active ? ACTIVE_BG : colors.inputBackground }]}
        onPress={() => onChange(active ? 'off' : 'on')}
        activeOpacity={0.7}
      >
        <ThinkIcon size={16} color={active ? ACTIVE_FG : colors.textMuted} />
        <Text style={[styles.label, { color: active ? ACTIVE_FG : colors.textMuted }]}>
          思考
        </Text>
      </TouchableOpacity>
    );
  }

  // effort / adaptive: pill + picker
  const active = current !== 'off';
  const options = EFFORT_LEVELS_BY_CAPABILITY[capability];

  return (
    <>
      <TouchableOpacity
        style={[styles.pill, { backgroundColor: active ? ACTIVE_BG : colors.inputBackground }]}
        onPress={() => setPickerVisible(true)}
        activeOpacity={0.7}
      >
        <ThinkIcon size={16} color={active ? ACTIVE_FG : colors.textMuted} />
        <Text style={[styles.label, { color: active ? ACTIVE_FG : colors.textMuted }]}>
          {SHORT_LABEL[current]}
        </Text>
      </TouchableOpacity>
      <EffortPicker
        visible={pickerVisible}
        options={options}
        current={current}
        onSelect={onChange}
        onClose={() => setPickerVisible(false)}
      />
    </>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 18,
    gap: 6,
  },
  label: {
    fontSize: 14,
    fontWeight: '500',
  },
});
