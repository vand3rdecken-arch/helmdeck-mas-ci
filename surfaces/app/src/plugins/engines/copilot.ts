// Copilot engine — the board/PM chat backend, behind the same Engine contract.
// Wraps the existing /chat endpoints (history + live + say) the daemon already
// serves; this is the app-side collapse of the scattered `import copilot`
// branches. No new daemon behaviour.

import { KEYS, type Engine, type Plugin } from "@/kernel";
import type { ApiClient } from "@/kernel";

function makeCopilot(api: ApiClient): Engine {
  const post = api.post as <T>(path: string, body?: unknown) => Promise<T>;
  const get = api.get as <T>(path: string) => Promise<T>;
  return {
    id: "engines.copilot",
    label: "Board Copilot",
    available: () => true,
    async spawn(cardId, brief) {
      // the board copilot is session-per-user, not per-card; spawn == open chat.
      await post(`/chat/say`, { first: brief });
      return { sessionId: cardId || "board" };
    },
    async send(_sessionId, message) {
      await post(`/chat/say`, { text: message });
    },
    async history(user) {
      return get<unknown[]>(`/chat/history?user=${encodeURIComponent(user)}`);
    },
  };
}

export const copilotEngine: Plugin = {
  id: "engines.copilot",
  tier: "plugin",
  inject: [KEYS.API.id, KEYS.ENGINES.id],
  register(scope) {
    const api = scope.require(KEYS.API);
    const engines = scope.require(KEYS.ENGINES);
    scope.use(engines.add("engines.copilot", "engines.copilot", makeCopilot(api)));
  },
};
