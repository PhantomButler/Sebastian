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
  isFirst?: boolean;
  isLast?: boolean;
  showLine?: boolean;
}

const DOT_COLOR: Record<Props['status'], string> = {
  running: '#f5a623',
  done: '#66bb6a',
  failed: '#f44336',
};

const DOT_SIZE = 8;
const DOT_RADIUS = DOT_SIZE / 2;
const HEADER_MIN_HEIGHT = 24;
/** Space above the dot so its center aligns with header text center. */
const GUTTER_TOP = (HEADER_MIN_HEIGHT - DOT_SIZE) / 2;

/** Priority-ordered param keys to extract per tool name. */
const KEY_PRIORITY: Record<string, string[]> = {
  Bash:              ['command'],
  Read:              ['file_path'],
  Write:             ['file_path'],
  Edit:              ['file_path'],
  Grep:              ['pattern', 'path'],
  Glob:              ['pattern', 'path'],
  delegate_to_agent: ['agent_type'],
  spawn_sub_agent:   ['goal'],
};

const GENERIC_KEYS = ['command', 'file_path', 'path', 'pattern', 'query'];

/**
 * 工具名 → header 展示的 (title, summary) 映射，与 Android `ToolDisplayName.kt` 对齐。
 * 大多数工具名本身是 PascalCase（Read/Write/Bash…），直接用作标题；少数 snake_case
 * 工具（delegate_to_agent / spawn_sub_agent）改写成「类别 + 目标」的形式，并把
 * agent_type 做 capitalize 显示。
 */
function resolveToolDisplay(
  toolName: string,
  rawSummary: string,
): { title: string; summary: string } {
  if (toolName === 'delegate_to_agent') {
    const capitalized = rawSummary
      ? rawSummary.charAt(0).toUpperCase() + rawSummary.slice(1)
      : '';
    return { title: `Agent: ${capitalized}`, summary: '' };
  }
  if (toolName === 'spawn_sub_agent') {
    return { title: 'Worker', summary: rawSummary };
  }
  return { title: toolName, summary: rawSummary };
}

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

  if (lines.length === 0) {
    for (const [key, val] of Object.entries(parsed)) {
      if (typeof val === 'string' && val.trim()) {
        lines.push(`${key}: ${val.trim()}`);
      }
    }
  }

  return lines.join('\n');
}

export function ToolCallRow({ name, input, status, result, isFirst, isLast, showLine }: Props) {
  const colors = useTheme();
  const [expanded, setExpanded] = useState(false);
  const rawSummary = extractInputSummary(name, input);
  const { title: displayTitle, summary: inputSummary } = resolveToolDisplay(name, rawSummary);

  const hasResult = result != null && result.trim().length > 0;
  const showOutput = status === 'running' || hasResult;
  const lineColor = colors.border;

  return (
    <View style={styles.row}>
      {/* Timeline gutter: top line segment → dot → bottom line segment */}
      <View style={styles.gutter}>
        <View
          style={[
            styles.gutterTop,
            showLine && !isFirst && { backgroundColor: lineColor },
          ]}
        />
        <View style={[styles.dot, { backgroundColor: DOT_COLOR[status] }]} />
        <View
          style={[
            styles.gutterBottom,
            showLine && !isLast && { backgroundColor: lineColor },
          ]}
        />
      </View>

      {/* Content column */}
      <View style={styles.content}>
        <Pressable
          style={styles.headerRow}
          onPress={() => setExpanded((prev) => !prev)}
          hitSlop={4}
        >
          <Text style={[styles.name, { color: colors.textSecondary }]}>{displayTitle}</Text>
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

        {expanded && (
          <View style={styles.detailArea}>
            <View style={styles.section}>
              <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>参数</Text>
              <CollapsibleContent content={extractKeyParams(name, input)} />
            </View>

            {showOutput && (
              <View style={styles.section}>
                <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>输出</Text>
                {status === 'running' ? (
                  <View style={styles.loadingRow}>
                    <Text style={{ color: DOT_COLOR.running, fontSize: 12 }}>●</Text>
                    <Text style={[styles.loadingText, { color: colors.textMuted }]}>执行中…</Text>
                  </View>
                ) : (
                  <CollapsibleContent content={result ?? ''} />
                )}
              </View>
            )}
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
  },
  gutter: {
    width: DOT_SIZE,
    alignItems: 'center',
  },
  gutterTop: {
    height: GUTTER_TOP,
    width: 1,
  },
  dot: {
    width: DOT_SIZE,
    height: DOT_SIZE,
    borderRadius: DOT_RADIUS,
  },
  gutterBottom: {
    flex: 1,
    width: 1,
  },
  content: {
    flex: 1,
    marginLeft: 8,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: HEADER_MIN_HEIGHT,
    gap: 8,
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
