import Markdown from 'react-native-markdown-display';
import { useTheme, useIsDark } from '../../theme/ThemeContext';
import { CodeBlock } from './CodeBlock';

interface Props {
  content: string;
  /** 流式未完成时传 true */
  streaming?: boolean;
}

export function MarkdownContent({ content }: Props) {
  const colors = useTheme();
  const isDark = useIsDark();

  const mdStyles = {
    body: { color: colors.text, fontSize: 16, lineHeight: 26 },
    heading1: { color: colors.text, fontSize: 20, fontWeight: '700' as const, marginBottom: 8 },
    heading2: { color: colors.text, fontSize: 17, fontWeight: '600' as const, marginBottom: 6 },
    heading3: { color: colors.text, fontSize: 15, fontWeight: '600' as const, marginBottom: 4 },
    strong: { color: colors.text, fontWeight: '700' as const },
    em: { fontStyle: 'italic' as const },
    code_inline: {
      backgroundColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.06)',
      color: isDark ? '#a8d8a8' : '#007AFF',
      fontFamily: 'monospace',
      fontSize: 13,
    },
    // fence/code_block styles kept as fallback; actual rendering overridden by rules
    fence: {
      backgroundColor: isDark ? '#1E1E2E' : '#F6F8FA',
      padding: 12,
      borderRadius: 8,
      marginVertical: 8,
    },
    code_block: {
      color: isDark ? '#D4D4D4' : '#383A42',
      fontFamily: 'monospace',
      fontSize: 13,
      lineHeight: 20,
    },
    bullet_list: { marginVertical: 4 },
    ordered_list: { marginVertical: 4 },
    list_item: { color: colors.text, marginBottom: 2 },
    blockquote: {
      borderLeftWidth: 3,
      borderLeftColor: colors.border,
      paddingLeft: 12,
      marginVertical: 6,
      opacity: 0.8,
    },
    hr: { borderTopColor: colors.border, borderTopWidth: 1, marginVertical: 12 },
    link: { color: colors.accent, textDecorationLine: 'underline' as const },
    table: { borderWidth: 1, borderColor: colors.border, marginVertical: 8 },
    th: { backgroundColor: colors.secondaryBackground, padding: 8, color: colors.text, fontWeight: '600' as const },
    td: { padding: 8, color: colors.text, borderTopWidth: 1, borderTopColor: colors.border },
  };

  const rules = {
    fence: (node: any) => {
      const code = node.content ?? '';
      const language = node.sourceInfo ?? '';
      return <CodeBlock key={node.key} code={code} language={language} />;
    },
  };

  return (
    <Markdown style={mdStyles} rules={rules}>{content}</Markdown>
  );
}
