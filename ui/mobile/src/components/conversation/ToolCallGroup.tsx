import { View, StyleSheet } from 'react-native';
import { ToolCallRow } from './ToolCallRow';
import { useTheme } from '../../theme/ThemeContext';
import type { RenderBlock } from '../../types';

type ToolBlock = Extract<RenderBlock, { type: 'tool' }>;

interface Props {
  tools: ToolBlock[];
}

export function ToolCallGroup({ tools }: Props) {
  const colors = useTheme();
  return (
    <View style={styles.container}>
      {tools.map((tool, index) => (
        <View key={tool.toolId}>
          <ToolCallRow
            name={tool.name}
            input={tool.input}
            status={tool.status}
            result={tool.result}
          />
          {/* Vertical connector between consecutive tool calls */}
          {index < tools.length - 1 && <View style={{ ...styles.connector, backgroundColor: colors.border }} />}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: 2,
    paddingLeft: 4,
  },
  connector: {
    width: 1,
    height: 10,
    marginLeft: 3,   // aligns with center of the 8px dot
  },
});
