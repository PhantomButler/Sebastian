import { Tabs } from 'expo-router';

export default function TabLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false }}>
      <Tabs.Screen
        name="chat/index"
        options={{ title: 'Sebastian', tabBarLabel: 'Sebastian' }}
      />
      <Tabs.Screen
        name="subagents/index"
        options={{ title: 'Sub-Agents', tabBarLabel: 'Sub-Agents' }}
      />
      <Tabs.Screen
        name="settings/index"
        options={{ title: '设置', tabBarLabel: '设置' }}
      />
    </Tabs>
  );
}
