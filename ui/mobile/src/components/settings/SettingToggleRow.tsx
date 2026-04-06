import { View, Text, StyleSheet } from 'react-native';
import { IOSSwitch } from '../common/IOSSwitch';
import { useTheme } from '../../theme/ThemeContext';

interface Props {
  label: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  disabled?: boolean;
  hasBorder?: boolean;
}

export function SettingToggleRow({
  label,
  value,
  onValueChange,
  disabled,
  hasBorder = false,
}: Props) {
  const colors = useTheme();
  return (
    <View
      style={[
        styles.row,
        hasBorder && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
      ]}
    >
      <Text style={[styles.label, { color: colors.text }]}>{label}</Text>
      <IOSSwitch value={value} onValueChange={onValueChange} disabled={disabled} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 52,
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  label: { fontSize: 17 },
});
