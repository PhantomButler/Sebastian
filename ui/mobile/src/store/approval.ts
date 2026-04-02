import { create } from 'zustand';
import { apiClient } from '../api/client';
import type { Approval } from '../types';

interface ApprovalState {
  pending: Approval | null;
  setPending: (approval: Approval | null) => void;
  grant: () => Promise<void>;
  deny: () => Promise<void>;
}

export const useApprovalStore = create<ApprovalState>((set, get) => ({
  pending: null,

  setPending: (approval) => set({ pending: approval }),

  grant: async () => {
    const { pending } = get();
    if (!pending) return;
    await apiClient.post(`/api/v1/approvals/${pending.id}/grant`);
    set({ pending: null });
  },

  deny: async () => {
    const { pending } = get();
    if (!pending) return;
    await apiClient.post(`/api/v1/approvals/${pending.id}/deny`);
    set({ pending: null });
  },
}));
