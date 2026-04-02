import { Modal, View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import type { Approval } from '../../types';

interface Props {
  approval: Approval | null;
  onGrant: () => void;
  onDeny: () => void;
}

export function ApprovalModal({ approval, onGrant, onDeny }: Props) {
  if (!approval) return null;
  return (
    <Modal transparent animationType="fade" visible>
      <View style={styles.overlay}>
        <View style={styles.card}>
          <Text style={styles.title}>需要你的决策</Text>
          <Text style={styles.desc}>{approval.description}</Text>
          <View style={styles.row}>
            <TouchableOpacity style={[styles.btn, styles.deny]} onPress={onDeny}>
              <Text style={styles.btnText}>拒绝</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.btn, styles.grant]} onPress={onGrant}>
              <Text style={styles.btnText}>批准</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', alignItems: 'center', justifyContent: 'center' },
  card: { backgroundColor: '#fff', borderRadius: 12, padding: 24, width: '85%' },
  title: { fontSize: 16, fontWeight: 'bold', marginBottom: 12 },
  desc: { color: '#333', marginBottom: 24, lineHeight: 20 },
  row: { flexDirection: 'row', gap: 12 },
  btn: { flex: 1, padding: 12, borderRadius: 8, alignItems: 'center' },
  grant: { backgroundColor: '#007AFF' },
  deny: { backgroundColor: '#FF3B30' },
  btnText: { color: '#fff', fontWeight: 'bold' },
});
