// ui/mobile/src/theme/colors.ts

export interface ThemeColors {
  // Backgrounds
  background: string;
  secondaryBackground: string;
  settingsBackground: string;
  cardBackground: string;
  inputBackground: string;

  // Text
  text: string;
  textSecondary: string;
  textMuted: string;

  // Borders
  border: string;
  borderLight: string;

  // Accent & Status
  accent: string;
  error: string;
  success: string;

  // User Bubble (ChatGPT style)
  userBubbleBg: string;
  userBubbleText: string;

  // Input
  inputBorder: string;

  // Sidebar
  overlay: string;
  activeSessionBg: string;

  // Buttons
  disabledButton: string;

  // Destructive
  destructiveBg: string;

  // Segmented control
  segmentedBg: string;

  // Shadow
  shadowColor: string;
}

export const lightColors: ThemeColors = {
  background: '#FFFFFF',
  secondaryBackground: '#FFFFFF',
  settingsBackground: '#F2F2F7',
  cardBackground: '#FFFFFF',
  inputBackground: '#F2F2F7',

  text: '#111111',
  textSecondary: '#8E8E93',
  textMuted: '#999999',

  border: '#D1D1D6',
  borderLight: '#E0E0E0',

  accent: '#007AFF',
  error: '#FF3B30',
  success: '#34C759',

  userBubbleBg: '#111111',
  userBubbleText: '#FFFFFF',

  inputBorder: '#CCCCCC',

  overlay: 'rgba(0,0,0,0.4)',
  activeSessionBg: '#E8F0FE',

  disabledButton: '#888888',

  destructiveBg: '#FFF2F1',

  segmentedBg: '#F2F2F7',

  shadowColor: '#000000',
};

export const darkColors: ThemeColors = {
  background: '#000000',
  secondaryBackground: '#111113',
  settingsBackground: '#000000',
  cardBackground: '#2C2C2E',
  inputBackground: '#2C2C2E',

  text: '#F5F5F5',
  textSecondary: '#8E8E93',
  textMuted: '#666666',

  border: '#38383A',
  borderLight: '#38383A',

  accent: '#0A84FF',
  error: '#FF453A',
  success: '#30D158',

  userBubbleBg: '#35353A',
  userBubbleText: '#FFFFFF',

  inputBorder: '#38383A',

  overlay: 'rgba(0,0,0,0.6)',
  activeSessionBg: '#1A3A5C',

  disabledButton: '#555555',

  destructiveBg: '#3A2020',

  segmentedBg: '#2C2C2E',

  shadowColor: '#AAAAAA',
};
