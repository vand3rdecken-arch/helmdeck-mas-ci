// Claude engine plugin — the first backend collapsed behind the Engine
// contract. Thin client of the daemon's existing endpoints (the app never runs
// the agent). This is what the scattered `import claude_sessions` branches
// become on the app side; copilot/deepseek follow the same shape.

import { KEYS, type Engine, type Plugin } from "@/kernel";
import type { ApiClient } from "@/kernel";

function makeClaude(api: ApiClient): Engine {
  const post = api.post as <T>(path: string, body?: unknown) => Promise<T>;
  const get = api.get as <T>(path: string) => Promise<T>;
  return {
    id: "engines.claude",
    label: "Claude Code",
    available: () => true,
    async spawn(cardId, brief) {
      const r = await post<{ id?: string }>(`/tracks/${cardId}/spawn`, brief);
      return { sessionId: r.id ?? cardId };
    },
    async send(sessionId, message) {
      await post(`/tracks/${sessionId}/say`, { text: message });
    },
    async history(user) {
      return get<unknown[]>(`/chat/history?user=${encodeURIComponent(user)}`);
    },
  };
}

export const claudeEngine: Plugin = {
  id: "engines.claude",
  tier: "plugin",
  inject: [KEYS.API.id, KEYS.ENGINES.id],
  register(scope) {
    const api = scope.require(KEYS.API);
    const engines = scope.require(KEYS.ENGINES);
    scope.use(engines.add("engines.claude", "engines.claude", makeClaude(api)));
    scope.emit("engine:selected", { cardId: "", engineId: "engines.claude" });
  },
};
