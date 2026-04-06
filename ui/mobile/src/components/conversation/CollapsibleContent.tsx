import { useState } from 'react';
import { Text, Pressable, StyleSheet } from 'react-native';
import { RightArrowIcon } from '../common/Icons';
import { useTheme } from '../../theme/ThemeContext';

const LINE_THRESHOLD = 5;
const MAX_LINES = 30;

interface Props {
  content: string;
}

export function CollapsibleContent({ content }: Props) {
  const colors = useTheme();
  const [expanded, setExpanded] = useState(false);

  if (!content.trim()) return null;

  const allLines = content.split('\n');
  const totalLines = allLines.length;
  const needsCollapse = totalLines > LINE_THRESHOLD;

  // No collapse needed — show everything directly
  if (!needsCollapse) {
    return (
      <Text style={[styles.contentText, { color: colors.textMuted }]}>
        {content}
      </Text>
    );
  }

  // Collapsed: show first line + arrow
  if (!expanded) {
    const firstLine = allLines[0];
    return (
      <Pressable
        style={styles.collapsedRow}
        onPress={() => setExpanded(true)}
        hitSlop={4}
      >
        <Text
          style={[styles.contentText, { color: colors.textMuted, flex: 1 }]}
          numberOfLines={1}
        >
          {firstLine}
        </Text>
        <RightArrowIcon size={10} color={colors.textMuted} />
      </Pressable>
    );
  }

  // Expanded: show up to MAX_LINES, click entire block to collapse
  const displayLines = allLines.slice(0, MAX_LINES);
  const isTruncated = totalLines > MAX_LINES;
  const displayText = displayLines.join('\n');

  return (
    <Pressable onPress={() => setExpanded(false)}>
      <Text style={[styles.contentText, { color: colors.textMuted }]}>
        {displayText}
        {isTruncated ? `\n… (共 ${totalLines} 行)` : ''}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  collapsedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  contentText: {
    fontFamily: 'monospace',
    fontSize: 12,
    lineHeight: 18,
  },
});
