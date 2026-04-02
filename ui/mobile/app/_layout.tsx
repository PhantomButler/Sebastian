import { Stack } from 'expo-router';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StyleSheet } from 'react-native';
import { useEffect } from 'react';
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useSettingsStore } from '@/src/store/settings';
import { registerDevice, grantApproval, denyApproval } from '@/src/api/approvals';
import { useSSE } from '@/src/hooks/useSSE';
import { useApprovalStore } from '@/src/store/approval';
import { ApprovalModal } from '@/src/components/common/ApprovalModal';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 2, staleTime: 30_000 } },
});

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

function AppInit({ children }: { children: React.ReactNode }) {
  const { load, jwtToken } = useSettingsStore();
  const { pending, setPending } = useApprovalStore();
  useSSE();

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!jwtToken) return;
    (async () => {
      const { status } = await Notifications.requestPermissionsAsync();
      if (status !== 'granted') return;
      const token = (await Notifications.getDevicePushTokenAsync()).data;
      await registerDevice(token).catch(() => {});
    })();
  }, [jwtToken]);

  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = response.notification.request.content.data as Record<string, string>;
      if (data?.type === 'approval.required') router.push('/(tabs)/chat');
      else if (data?.type?.startsWith('task.')) router.push('/(tabs)/subagents');
    });
    return () => sub.remove();
  }, []);

  async function handleGrant() {
    if (!pending) return;
    await grantApproval(pending.id).catch(() => {});
    setPending(null);
  }

  async function handleDeny() {
    if (!pending) return;
    await denyApproval(pending.id).catch(() => {});
    setPending(null);
  }

  return (
    <>
      {children}
      <ApprovalModal approval={pending} onGrant={handleGrant} onDeny={handleDeny} />
    </>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <GestureHandlerRootView style={styles.root}>
        <QueryClientProvider client={queryClient}>
          <AppInit>
            <Stack screenOptions={{ headerShown: false }} />
          </AppInit>
        </QueryClientProvider>
      </GestureHandlerRootView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
