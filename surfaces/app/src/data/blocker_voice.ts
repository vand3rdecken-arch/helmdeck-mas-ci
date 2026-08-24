import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";

// Proactive blocker announcements over the phone's own audio route (More ->
// Voice). OFF by default, like every other proactive channel in this app
// (glance_decide, glance_talk, relay.url) - the owner opts in rather than
// discovering a talking phone. The clip is server-rendered (spine/
// media/voice.py via POST /notify/speak) and played with data/voice.ts's
// speak(), which is the SAME native player the chat voice mode already
// ships - this toggle only decides whether a fresh push also triggers it.
const PREF_KEY = "helmdeck.blockerVoice";   // AsyncStorage: "1" = on, "0"/absent = off

interface BlockerVoiceState {
  enabled: boolean;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  setEnabled: (v: boolean) => void;
}

export const useBlockerVoice = create<BlockerVoiceState>((set) => ({
  enabled: false,
  hydrated: false,
  hydrate: async () => {
    try {
      const raw = await AsyncStorage.getItem(PREF_KEY);
      if (raw !== null) set({ enabled: raw === "1" });
    } catch { /* unavailable -> keep default (off) */ }
    set({ hydrated: true });
  },
  setEnabled: (v) => {
    set({ enabled: v });
    AsyncStorage.setItem(PREF_KEY, v ? "1" : "0").catch(() => { /* best effort */ });
  },
}));
