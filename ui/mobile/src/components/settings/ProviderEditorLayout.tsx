import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Keyboard,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { BackButton } from '@/src/components/common/BackButton';
import { useTheme } from '@/src/theme/ThemeContext';

interface Props {
  title: string;
  subtitle: string;
  children: ReactNode;
  onDone?: () => void;
  doneDisabled?: boolean;
  doneLoading?: boolean;
}

export function ProviderEditorLayout({
  title,
  subtitle,
  children,
  onDone,
  doneDisabled = false,
  doneLoading = false,
}: Props) {
  const insets = useSafeAreaInsets();
  const colors = useTheme();
  const floatingHeaderTop = insets.top + 8;
  const floatingHeaderHeight = 44;
  const contentTopPadding = floatingHeaderTop + floatingHeaderHeight + 28;

  return (
    <SafeAreaView style={[styles.screen, { backgroundColor: colors.settingsBackground }]} edges={['bottom']}>
      <View style={[styles.floatingHeader, { top: floatingHeaderTop }]}>
        <BackButton style={styles.backButton} />
        {onDone ? (
          <TouchableOpacity
            style={[
              styles.doneButton,
              {
                backgroundColor: doneDisabled ? colors.inputBackground : colors.accent,
                opacity: doneDisabled ? 0.75 : 1,
              },
            ]}
            onPress={() => { Keyboard.dismiss(); onDone?.(); }}
            disabled={doneDisabled}
            activeOpacity={0.8}
          >
            {doneLoading ? (
              <ActivityIndicator color="#FFFFFF" size="small" />
            ) : (
              <Text
                style={[
                  styles.doneText,
                  { color: doneDisabled ? colors.textSecondary : '#FFFFFF' },
                ]}
              >
                完成
              </Text>
            )}
          </TouchableOpacity>
        ) : null}
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[
          styles.container,
          { paddingTop: contentTopPadding, paddingBottom: insets.bottom + 32 },
        ]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.hero}>
          <Text style={[styles.heroTitle, { color: colors.text }]}>{title}</Text>
          <Text style={[styles.heroSubtitle, { color: colors.textSecondary }]}>{subtitle}</Text>
        </View>

        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  scroll: { flex: 1 },
  container: { paddingHorizontal: 16 },
  floatingHeader: {
    position: 'absolute',
    left: 16,
    right: 16,
    zIndex: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  backButton: {
    minHeight: 36,
    justifyContent: 'center',
  },
  doneButton: {
    minWidth: 74,
    height: 36,
    borderRadius: 18,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  doneText: {
    fontSize: 15,
    fontWeight: '600',
  },
  hero: {
    marginBottom: 20,
    paddingHorizontal: 4,
  },
  heroTitle: {
    fontSize: 34,
    fontWeight: '700',
  },
  heroSubtitle: {
    marginTop: 6,
    fontSize: 15,
    lineHeight: 21,
  },
});
