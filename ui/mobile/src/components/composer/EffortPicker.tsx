import { Modal, View, Text, TouchableOpacity, StyleSheet, Pressable } from 'react-native';
import { useIsDark, useTheme } from '../../theme/ThemeContext';
import type { ThinkingEffort } from '../../types';

interface Props {
  visible: boolean;
  options: readonly ThinkingEffort[];
  current: ThinkingEffort;
  onSelect: (effort: ThinkingEffort) => void;
  onClose: () => void;
}

const LABELS: Record<ThinkingEffort, string> = {
  off: '关闭',
  on: '开启',
  low: '低 — 少量思考',
  medium: '中 — 适度思考',
  high: '高 — 深度思考',
  max: '最大 — 无约束思考',
};

export function EffortPicker({ visible, options, current, onSelect, onClose }: Props) {
  const colors = useTheme();
  const isDark = useIsDark();
  const activeBackground = isDark ? '#FFFFFF' : '#111111';
  const activeForeground = isDark ? '#111111' : '#FFFFFF';

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      presentationStyle="overFullScreen"
      statusBarTranslucent
      navigationBarTranslucent
      onRequestClose={onClose}
    >
      <Pressable style={[styles.backdrop, { backgroundColor: colors.overlay }]} onPress={onClose}>
        <Pressable
          style={[styles.sheet, { backgroundColor: colors.background }]}
          onPress={(e) => e.stopPropagation()}
        >
          <Text style={[styles.title, { color: colors.text }]}>思考深度</Text>
          {options.map((opt) => {
            const active = opt === current;
            return (
              <TouchableOpacity
                key={opt}
                style={[
                  styles.option,
                  active && { backgroundColor: activeBackground },
                ]}
                onPress={() => {
                  onSelect(opt);
                  onClose();
                }}
                activeOpacity={0.7}
              >
                <Text
                  style={[
                    styles.optionLabel,
                    { color: active ? activeForeground : colors.text },
                  ]}
                >
                  {LABELS[opt]}
                </Text>
              </TouchableOpacity>
            );
          })}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  sheet: {
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    paddingBottom: 32,
  },
  title: {
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 12,
    textAlign: 'center',
  },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    paddingHorizontal: 12,
    borderRadius: 10,
  },
  optionLabel: {
    fontSize: 15,
  },
});
