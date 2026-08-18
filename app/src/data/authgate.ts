import { create } from "zustand";

// Global "you need to sign in" gate. Restores what the old Next.js web app's
// AuthGate component (web/components/auth.tsx, archived at the Expo cutover,
// commit 6625edc) used to do - that component was never ported, so once a
// token went bad there was no way back into the app short of a fresh pairing
// link from another device. Fed by client.ts's 401 detection (the ONE place
// that already classifies AuthRequired) and by Settings' logout button - one
// mechanism, two triggers, same shape as data/health.ts's useHealth store.
interface AuthGateState {
  needsLogin: boolean;
  reportAuthRequired: () => void;
  clearAuthRequired: () => void;
}

export const useAuthGate = create<AuthGateState>((set) => ({
  needsLogin: false,
  reportAuthRequired: () => set({ needsLogin: true }),
  clearAuthRequired: () => set({ needsLogin: false }),
}));
