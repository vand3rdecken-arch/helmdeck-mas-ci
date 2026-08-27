// Phase 2 of the cell-registry decree (daemon/debt.py order 33): the PM cell's
// Surface. Same strangler-wrap pattern as connectors.tsx/board.tsx - no data-
// fetching logic rewritten, only composed and registered. Unlike Connectors
// (one existing screen), PM's working UI is split across two existing pieces:
// the status readout (ui/pm_panel.tsx's PMStatusPanel, also embedded in the
// dashboard tile) and the loop map (app/loopmap.tsx's LoopMapScreen, the
// pipeline/build-loop/laws view). This surface composes both into one PM
// dashboard component, reusing each unmodified - the daemon PM cell
// (cells.py, surface="surfaces.pm") owns /pm/* routes that both pull
// from (api.pmPlan / api.loopMap), so nothing here duplicates that fetching.

import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import LoopMapScreen from "@/app/loopmap";
import { PMStatusPanel } from "@/ui/pm_panel";
import { useTheme } from "@/theme";
import { KEYS, type Plugin, type Surface } from "@/kernel";

/** PM dashboard: the status readout on top, the full loop map below. Both
 *  pieces already scroll/fetch on their own; PMStatusPanel is short and
 *  renders nothing when the loop is quiet, so stacking it above the loop map
 *  in one screen reads as "status, then the machine that produces it". */
function PmDashboard() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <ScrollView contentContainerStyle={{ paddingTop: insets.top + 10, paddingHorizontal: 12, paddingBottom: 4 }}>
        <PMStatusPanel />
      </ScrollView>
      <View style={{ flex: 1 }}>
        <LoopMapScreen />
      </View>
    </View>
  );
}

const pm: Surface = {
  id: "surfaces.pm",
  title: "PM",
  path: "/(tabs)/pm",
  component: PmDashboard as Surface["component"],
  // No `route` here on purpose (mirrors connectors.tsx): today PM has no
  // standalone nav.tabs slot of its own (loopmap is reached from Automation),
  // so this Surface is deliberately not wired into the tab bar yet - it exists
  // so the cell registry has a real app-side counterpart to gate/inspect. A
  // future nav.tabs entry can add `route` without touching this file.
  nav: { group: "primary", order: 13, icon: "compass-outline" },
};

export const pmSurface: Plugin = {
  id: "surfaces.pm",
  tier: "plugin",
  inject: [KEYS.SURFACES.id],
  register(scope) {
    const surfaces = scope.require(KEYS.SURFACES);
    scope.use(surfaces.add(pm.id, pm.id, pm));
    scope.emit("surface:changed", { surfaceId: pm.id, present: true });
  },
};
