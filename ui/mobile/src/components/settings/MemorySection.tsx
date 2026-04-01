import { View, Text, StyleSheet } from 'react-native';

export function MemorySection() {
  return (
    <View style={styles.section}>
      <Text style={styles.label}>Memory 管理</Text>
      <Text style={styles.placeholder}>即将推出</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginBottom: 24 },
  label: { fontWeight: 'bold', marginBottom: 4 },
  placeholder: { color: '#999' },
});
