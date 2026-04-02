import { useEffect, type ReactNode } from 'react';
import * as Notifications from 'expo-notifications';
import { router, Stack } from 'expo-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { registerDevice } from '@/src/api/approvals';
import { ApprovalModal } from '@/src/components/common/ApprovalModal';
import { useSSE } from '@/src/hooks/useSSE';
import { useApprovalStore } from '@/src/store/approval';
import { useSettingsStore } from '@/src/store/settings';

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

function AppInit({ children }: { children: ReactNode }) {
  const { load, jwtToken } = useSettingsStore();
  const { pending, grant, deny, setPending } = useApprovalStore();

  useSSE({
    onApprovalRequired: (approval) => setPending(approval),
  });

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!jwtToken) return;
    void (async () => {
      const { status } = await Notifications.requestPermissionsAsync();
      if (status !== 'granted') return;
      const token = (await Notifications.getDevicePushTokenAsync()).data;
      await registerDevice(token).catch(() => {});
    })();
  }, [jwtToken]);

  useEffect(() => {
    const subscription = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        const data = response.notification.request.content.data as Record<string, string>;
        if (data?.type === 'approval.required') {
          router.push('/(tabs)/chat');
        } else if (data?.type?.startsWith('task.')) {
          router.push('/(tabs)/subagents');
        }
      },
    );
    return () => subscription.remove();
  }, []);

  return (
    <>
      {children}
      <ApprovalModal approval={pending} onGrant={grant} onDeny={deny} />
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
