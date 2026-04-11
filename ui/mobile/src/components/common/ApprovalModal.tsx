import { Modal, View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
import type { Approval } from '../../types';

interface Props {
  approval: Approval | null;
  onGrant: () => void;
  onDeny: () => void;
}

export function ApprovalModal({ approval, onGrant, onDeny }: Props) {
  const colors = useTheme();

  if (!approval) return null;

  return (
    <Modal transparent animationType="fade" visible onRequestClose={onDeny}>
      <View style={styles.overlay}>
        <View style={[styles.card, { backgroundColor: colors.cardBackground }]}>
          <Text style={[styles.title, { color: colors.text }]}>需要你的决策</Text>
          <Text style={[styles.message, { color: colors.textSecondary }]}>{approval.description}</Text>
          <View style={[styles.divider, { backgroundColor: colors.borderLight }]} />
          <View style={styles.row}>
            <TouchableOpacity
              style={[styles.btn, { borderRightWidth: 0.5, borderRightColor: colors.borderLight }]}
              onPress={onDeny}
              activeOpacity={0.6}
            >
              <Text style={[styles.btnText, { color: colors.error }]}>拒绝</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.btn} onPress={onGrant} activeOpacity={0.6}>
              <Text style={[styles.btnText, styles.grantText, { color: colors.accent }]}>批准</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: {
    width: '72%',
    borderRadius: 14,
    overflow: 'hidden',
  },
  title: {
    fontSize: 17,
    fontWeight: '600',
    textAlign: 'center',
    paddingTop: 20,
    paddingHorizontal: 20,
  },
  message: {
    fontSize: 13,
    lineHeight: 18,
    textAlign: 'center',
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 20,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
  },
  row: {
    flexDirection: 'row',
  },
  btn: {
    flex: 1,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnText: {
    fontSize: 17,
  },
  grantText: {
    fontWeight: '600',
  },
});
