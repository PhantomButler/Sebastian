import { useState } from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { useTheme } from '../../theme/ThemeContext';
import { RightArrowIcon } from '../common/Icons';
import { CollapsibleContent } from './CollapsibleContent';

interface Props {
  name: string;
  input: string;
  status: 'running' | 'done' | 'failed';
  result?: string;
}

const DOT_COLOR: Record<Props['status'], string> = {
  running: '#f5a623',
  done: '#4caf50',
  failed: '#f44336',
};

/** Priority-ordered param keys to extract per tool name. */
const KEY_PRIORITY: Record<string, string[]> = {
  Bash:              ['command'],
  Read:              ['file_path'],
  Write:             ['file_path'],
  Edit:              ['file_path'],
  Grep:              ['pattern', 'path'],
  Glob:              ['pattern', 'path'],
  delegate_to_agent: ['goal'],
};

const GENERIC_KEYS = ['command', 'file_path', 'path', 'goal', 'pattern', 'query'];

/** Extract a human-readable one-line summary from the JSON input string. */
function extractInputSummary(name: string, input: string): string {
  if (!input) return '';
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(input) as Record<string, unknown>;
  } catch {
    return input.length > 80 ? `${input.slice(0, 80)}…` : input;
  }

  const keys = KEY_PRIORITY[name] ?? GENERIC_KEYS;
  for (const key of keys) {
    const val = parsed[key];
    if (typeof val === 'string' && val.trim()) {
      const text = val.trim();
      return text.length > 80 ? `${text.slice(0, 80)}…` : text;
    }
  }

  for (const val of Object.values(parsed)) {
    if (typeof val === 'string' && val.trim()) {
      const text = val.trim();
      return text.length > 80 ? `${text.slice(0, 80)}…` : text;
    }
  }

  return '';
}

/** Extract key params as multi-line "key: value" string for the detail view. */
function extractKeyParams(name: string, input: string): string {
  if (!input) return '';
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(input) as Record<string, unknown>;
  } catch {
    return input;
  }

  const keys = KEY_PRIORITY[name] ?? GENERIC_KEYS;
  const lines: string[] = [];

  for (const key of keys) {
    const val = parsed[key];
    if (typeof val === 'string' && val.trim()) {
      lines.push(`${key}: ${val.trim()}`);
    }
  }

  // If no priority keys matched, try all string values
  if (lines.length === 0) {
    for (const [key, val] of Object.entries(parsed)) {
      if (typeof val === 'string' && val.trim()) {
        lines.push(`${key}: ${val.trim()}`);
      }
    }
  }

  return lines.join('\n');
}

export function ToolCallRow({ name, input, status, result }: Props) {
  const colors = useTheme();
  const [expanded, setExpanded] = useState(false);
  const inputSummary = extractInputSummary(name, input);

  const hasResult = result != null && result.trim().length > 0;
  const showOutput = status === 'running' || hasResult;

  return (
    <View>
      {/* Header row — always visible */}
      <Pressable
        style={styles.headerRow}
        onPress={() => setExpanded((prev) => !prev)}
        hitSlop={4}
      >
        <View style={[styles.dot, { backgroundColor: DOT_COLOR[status] }]} />
        <Text style={[styles.name, { color: colors.textSecondary }]}>{name}</Text>
        {inputSummary ? (
          <Text style={[styles.summary, { color: colors.textMuted }]} numberOfLines={1}>
            {inputSummary}
          </Text>
        ) : null}
        {expanded && (
          <RightArrowIcon
            size={12}
            color={colors.textMuted}
            style={{ transform: [{ rotate: '90deg' }] }}
          />
        )}
      </Pressable>

      {/* Expanded detail area */}
      {expanded && (
        <View style={styles.detailArea}>
          {/* Parameters section */}
          <View style={styles.section}>
            <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>参数</Text>
            <CollapsibleContent content={extractKeyParams(name, input)} />
          </View>

          {/* Output section */}
          {showOutput && (
            <View style={styles.section}>
              <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>输出</Text>
              {status === 'running' ? (
                <View style={styles.loadingRow}>
                  <Text style={{ color: DOT_COLOR.running, fontSize: 12 }}>●</Text>
                  <Text style={[styles.loadingText, { color: colors.textMuted }]}>执行中…</Text>
                </View>
              ) : (
                <CollapsibleContent content={result!} />
              )}
            </View>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    flexShrink: 0,
  },
  name: {
    fontSize: 13,
    fontWeight: '500',
    flexShrink: 0,
  },
  summary: {
    fontSize: 13,
    flex: 1,
  },
  detailArea: {
    paddingLeft: 16,
    paddingBottom: 4,
  },
  section: {
    marginTop: 6,
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: '600',
    marginBottom: 3,
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  loadingText: {
    fontSize: 12,
  },
});
