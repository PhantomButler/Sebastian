# Tool Call 可折叠交互 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 tool call 从平铺列表改为两层可折叠交互，折叠态只显示一行摘要，展开后显示关键参数和执行输出，超长内容有二级折叠。

**Architecture:** 在 `Icons.tsx` 新增 `RightArrowIcon`；新建 `CollapsibleContent.tsx` 处理 ≤5 行直接显示 / >5 行可折叠 / 上限 30 行的通用逻辑；重写 `ToolCallRow.tsx` 实现两层折叠交互；修改 `ToolCallGroup.tsx` 将竖线改为贯穿绝对定位。

**Tech Stack:** React Native, react-native-svg, TypeScript

---

## File Structure

| Operation | File | Responsibility |
|-----------|------|----------------|
| Modify | `src/components/common/Icons.tsx` | 新增 `RightArrowIcon` 组件 |
| Create | `src/components/conversation/CollapsibleContent.tsx` | 通用内容折叠组件（≤5 行直显，>5 行折叠，上限 30 行） |
| Rewrite | `src/components/conversation/ToolCallRow.tsx` | 两层折叠交互，参数/输出渲染 |
| Modify | `src/components/conversation/ToolCallGroup.tsx` | 竖线改为贯穿绝对定位 |

All paths relative to `ui/mobile/`.

---

### Task 1: Add RightArrowIcon to Icons.tsx

**Files:**
- Modify: `src/components/common/Icons.tsx`

- [ ] **Step 1: Add RightArrowIcon component**

Open `src/components/common/Icons.tsx` and add after the existing `DeleteIcon` function:

```tsx
// Path data from src/assets/icons/right_arrow.svg
export function RightArrowIcon({ size = 16, color = '#bbb', style }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" style={style}>
      <Path
        d="M296.8 856l357.8-344-357.8-344c-7.9-7.5-12.4-18-12.5-28.9 0-36.5 45.9-54.8 72.7-28.9l357.8 344c33.3 32 33.3 83.9 0 115.8L357 913.9c-26.8 25.8-72.7 7.5-72.7-28.9 0-11 4.5-21.4 12.5-29z"
        fill={color}
      />
    </Svg>
  );
}
```

- [ ] **Step 2: Verify the app still builds**

Run:
```bash
cd ui/mobile && npx expo start --clear
```
Expected: Metro bundler starts without errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/common/Icons.tsx
git commit -m "feat(icons): add RightArrowIcon component"
```

---

### Task 2: Create CollapsibleContent component

**Files:**
- Create: `src/components/conversation/CollapsibleContent.tsx`

This is a reusable component that handles the second-level collapse logic:
- Count lines by splitting on `\n`
- ≤5 lines: show all content, no arrow
- >5 lines: default collapsed (show first line truncated + ▶ arrow), click to expand
- Expanded: show up to 30 lines, truncated lines show `… (共 N 行)`, click the entire block to collapse
- Uses `RightArrowIcon` with `rotate(90deg)` when expanded

- [ ] **Step 1: Create CollapsibleContent.tsx**

Create file `src/components/conversation/CollapsibleContent.tsx`:

```tsx
import { useState } from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
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
```

- [ ] **Step 2: Verify the app still builds**

Run:
```bash
cd ui/mobile && npx expo start --clear
```
Expected: Metro bundler starts without errors. The component is not rendered yet but should compile.

- [ ] **Step 3: Commit**

```bash
git add src/components/conversation/CollapsibleContent.tsx
git commit -m "feat(conversation): add CollapsibleContent component for second-level folding"
```

---

### Task 3: Rewrite ToolCallRow with two-level collapsible interaction

**Files:**
- Rewrite: `src/components/conversation/ToolCallRow.tsx`

This is the core change. The component now:
- Accepts `result` prop (in addition to existing `name`, `input`, `status`)
- First level: click entire header row to expand/collapse
  - Collapsed (default): dot + name + summary, no arrow
  - Expanded: dot + name + summary + ▼ arrow, plus 「参数」and「输出」sections below
- Parameters section: extract key params using `KEY_PRIORITY`, display as `key: value` lines, wrapped in `CollapsibleContent`
- Output section: depends on status (running → loading indicator, done/failed with result → `CollapsibleContent`, no result → hidden)

- [ ] **Step 1: Rewrite ToolCallRow.tsx**

Replace the entire content of `src/components/conversation/ToolCallRow.tsx`:

```tsx
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
```

- [ ] **Step 2: Update ToolCallGroup to pass `result` prop**

Open `src/components/conversation/ToolCallGroup.tsx`. The current code passes `name`, `input`, `status` to `ToolCallRow` but not `result`. Add it:

Replace the `<ToolCallRow>` JSX inside the `.map()`:

```tsx
<ToolCallRow
  name={tool.name}
  input={tool.input}
  status={tool.status}
  result={tool.result}
/>
```

- [ ] **Step 3: Verify the app builds and renders**

Run:
```bash
cd ui/mobile && npx expo start --clear
```
Expected: Metro starts. Navigate to a conversation with tool calls. Each tool call should appear as a single line (collapsed). Tapping it should expand to show 参数 and 输出 sections.

- [ ] **Step 4: Commit**

```bash
git add src/components/conversation/ToolCallRow.tsx src/components/conversation/ToolCallGroup.tsx
git commit -m "feat(conversation): rewrite ToolCallRow with two-level collapsible interaction"
```

---

### Task 4: Modify ToolCallGroup for continuous vertical line

**Files:**
- Modify: `src/components/conversation/ToolCallGroup.tsx`

Change the vertical connector from disconnected segments between items to a single absolute-positioned line spanning from the first dot to the last dot. The dots sit on top of the line via `z-index`.

- [ ] **Step 1: Rewrite ToolCallGroup.tsx**

Replace the entire content of `src/components/conversation/ToolCallGroup.tsx`:

```tsx
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

  if (tools.length === 0) return null;

  return (
    <View style={styles.container}>
      {/* Continuous vertical line — absolute positioned behind the dots */}
      {tools.length > 1 && (
        <View
          style={[
            styles.verticalLine,
            { backgroundColor: colors.border },
          ]}
        />
      )}

      {tools.map((tool) => (
        <ToolCallRow
          key={tool.toolId}
          name={tool.name}
          input={tool.input}
          status={tool.status}
          result={tool.result}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'relative',
    paddingVertical: 2,
    paddingLeft: 4,
  },
  verticalLine: {
    position: 'absolute',
    left: 7,        // center of 8px dot at paddingLeft:4 → 4 + 3 = 7
    top: 8,         // vertically aligned with center of first dot (paddingVertical:4 + dot radius 4)
    bottom: 8,      // aligned with center of last dot
    width: 1,
    zIndex: 0,
  },
});
```

Note: The dot in `ToolCallRow` needs `zIndex: 1` to sit above the line. Update the dot style in `ToolCallRow.tsx`:

In `src/components/conversation/ToolCallRow.tsx`, update the `dot` style:

```tsx
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    flexShrink: 0,
    zIndex: 1,
  },
```

- [ ] **Step 2: Verify the continuous line renders correctly**

Run:
```bash
cd ui/mobile && npx expo start --clear
```
Expected: When a conversation has multiple consecutive tool calls, a continuous vertical line connects through all dots without gaps. Dots are visible on top of the line. Expanding a tool call makes the line stretch accordingly.

- [ ] **Step 3: Commit**

```bash
git add src/components/conversation/ToolCallGroup.tsx src/components/conversation/ToolCallRow.tsx
git commit -m "feat(conversation): continuous vertical line connecting tool calls"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| 2.1 极简风格，无卡片背景 | Task 3 — no card background, just rows |
| 2.1 竖线贯穿连接 | Task 4 — absolute-positioned continuous line |
| 2.1 RightArrowIcon | Task 1 — added to Icons.tsx |
| 2.2 第一层折叠态不显示箭头 | Task 3 — arrow only renders when `expanded` |
| 2.2 第一层展开时显示 ▼ 箭头（rotate 90deg） | Task 3 — `RightArrowIcon` with `rotate: '90deg'` |
| 2.2 第二层 ≤5 行直接显示 | Task 2 — `LINE_THRESHOLD = 5` check |
| 2.2 第二层 >5 行默认折叠 | Task 2 — collapsed state with first line + ▶ |
| 2.2 第二层展开后点击整块折叠 | Task 2 — `Pressable` wrapping expanded content |
| 2.2 最大 30 行上限 | Task 2 — `MAX_LINES = 30`, truncation with `… (共 N 行)` |
| 2.3 KEY_PRIORITY 关键参数 | Task 3 — `extractKeyParams` function |
| 2.4 running → loading 指示 | Task 3 — `● 执行中…` in amber color |
| 2.4 done + 无 result → 不显示输出 | Task 3 — `showOutput` conditional |
| 2.5 竖线贯穿 + z-index dot | Task 4 — absolute line + zIndex on dot |

### Placeholder Scan
No TBD, TODO, or placeholder patterns found.

### Type Consistency
- `Props` in ToolCallRow: `{ name, input, status, result }` — matches `ToolBlock` from `types.ts`
- `CollapsibleContent` props: `{ content: string }` — used consistently in Task 3
- `RightArrowIcon` props: `{ size, color, style }` — matches `IconProps` interface in Icons.tsx
- `extractInputSummary` and `extractKeyParams` both accept `(name: string, input: string)` — consistent
