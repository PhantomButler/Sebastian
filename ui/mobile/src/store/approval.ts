import { create } from 'zustand';
import type { Approval } from '../types';

interface ApprovalState {
  pending: Approval | null;
  setPending: (approval: Approval | null) => void;
}

export const useApprovalStore = create<ApprovalState>((set) => ({
  pending: null,
  setPending: (approval) => set({ pending: approval }),
}));
