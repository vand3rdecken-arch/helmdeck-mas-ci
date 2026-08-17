// DeepSeek engine — the NEW backend the whole modularization was for. The
// payoff of the seam: adding it is one file, zero edits to server.py/sessions.py
// or any surface. It stays unavailable() until the daemon grows a matching
// /engines/deepseek backend (spawn/say/history over deepseek-chat/reasoner);
// available() is manifest-gated so the UI hides it cleanly until then — no
// half-wired backend pretending to work (honest, not a stub that 500s).

import { KEYS, type Engine, type Plugin } from "@/kernel";
import type { ApiClient, Manifest } from "@/kernel";

function makeDeepSeek(api: ApiClient, manifest: Manifest): Engine {
  const post = api.post as <T>(path: string, body?: unknown) => Promise<T>;
  const get = api.get as <T>(path: string) => Promise<T>;
  return {
    id: "engines.deepseek",
    label: "DeepSeek",
    // shown only once the daemon advertises it in the manifest (Phase 3).
    available: () => manifest.engines.includes("engines.deepseek"),
    async spawn(cardId, brief) {
      const r = await post<{ id?: string }>(`/engines/deepseek/tracks/${cardId}/spawn`, brief);
      return { sessionId: r.id ?? cardId };
    },
    async send(sessionId, message) {
      await post(`/engines/deepseek/tracks/${sessionId}/say`, { text: message });
    },
    async history(user) {
      return get<unknown[]>(`/engines/deepseek/history?user=${encodeURIComponent(user)}`);
    },
  };
}

export const deepseekEngine: Plugin = {
  id: "engines.deepseek",
  tier: "plugin",
  inject: [KEYS.API.id, KEYS.ENGINES.id, KEYS.MANIFEST.id],
  register(scope) {
    const api = scope.require(KEYS.API);
    const manifest = scope.require(KEYS.MANIFEST);
    const engines = scope.require(KEYS.ENGINES);
    scope.use(engines.add("engines.deepseek", "engines.deepseek", makeDeepSeek(api, manifest)));
  },
};
