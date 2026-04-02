import { useQuery } from '@tanstack/react-query';
import { getSessions } from '../api/sessions';
import { useSettingsStore } from '../store/settings';

export function useSessions() {
  const jwtToken = useSettingsStore((s) => s.jwtToken);
  return useQuery({
    queryKey: ['sessions'],
    queryFn: getSessions,
    enabled: !!jwtToken,
  });
}
