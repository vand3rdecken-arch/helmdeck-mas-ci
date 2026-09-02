import { Ionicons } from "@expo/vector-icons";
import { Animated as RNAnimated, Easing, Pressable, Text, View } from "react-native";
import { useEffect, useMemo, useRef } from "react";

import type { HenrySegment, LoopMap, LoopNode, RepoView } from "@/data/client";
import { useT } from "@/i18n";
import { laneColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

/**
 * THE PIPELINE, as ONE component.
 *
 * Karte -> Arbeit -> Gate -> Abnahme -> Deploy, drawn once and reused by the
 * loop map and by repo onboarding. Two copies of this row is the failure this
 * whole redesign is a reaction to (the owner's "ich verstehe nicht, was
 * dahinter ist" came from screens that each described the machine slightly
 * differently), and the same rule the chat UI already lives under: never two
 * of the same surface.
 *
 * IT IS A PROJECTION, NOT A MODEL.
 * The station list, the order, which are on, and WHY one is off all arrive from
 * /loop/map?repo= (daemon: sessions.flow + projects.resolve). There is
 * deliberately no station array in this file. A hardcoded one is exactly the
 * duplication routes_info.py's comment was written against - and it is how the
 * old hand-typed loop map came to describe a board nobody had shipped for
 * months.
 *
 * READ-ONLY, ON PURPOSE.
 * Nothing here writes. Changing the pipeline goes through Henry (or the type
 * picker), because a second edit place for these keys is a binding non-goal of
 * the settings redesign. The footer says so instead of leaving the owner to
 * discover that the dots are not buttons.
 */

// The gate's ring pulses: "checked here". Same motion the loop map used, kept
// with the station rather than with the screen so both callers get it.
function GateDot({ color, dim }: { color: string; dim: boolean }) {
  const p = useRef(new RNAnimated.Value(0)).current;
  useEffect(() => {
    if (dim) return;
    const anim = RNAnimated.loop(RNAnimated.timing(p, {
      toValue: 1, duration: 1600, easing: Easing.out(Easing.quad), useNativeDriver: true,
    }));
    anim.start();
    return () => anim.stop();
  }, [p, dim]);
  const scale = p.interpolate({ inputRange: [0, 1], outputRange: [0.7, 1.9] });
  const op = p.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] });
  return (
    <View style={{ alignItems: "center", justifyContent: "center" }}>
      {!dim ? (
        <RNAnimated.View style={{ position: "absolute", width: 30, height: 30, borderRadius: 15,
          borderWidth: 2, borderColor: color, transform: [{ scale }], opacity: op }} />
      ) : null}
      <View style={{ width: 30, height: 30, borderRadius: 15, alignItems: "center",
        justifyContent: "center", backgroundColor: dim ? "transparent" : color,
        borderWidth: dim ? 1.5 : 0, borderColor: color,
        borderStyle: dim ? "dashed" : "solid" }}>
        <Ionicons name="shield-checkmark" size={16} color={dim ? color : "#fff"} />
      </View>
    </View>
  );
}

function stationColor(t: ThemeTokens, key: string): string {
  // gate and deploy are STEPS, not lanes, so they have no lane colour to
  // inherit - they get the two accents the rest of the app already uses for
  // "checked" and "shipped".
  if (key === "gate") return t.accent2;
  if (key === "deploy") return t.ok;
  return laneColor(t, key);
}

export interface PipelineProps {
  map?: LoopMap | null;
  /** Tapping a station reports it, so a host screen can show the detail card it
   *  already owns. Omit for a purely decorative row (the onboarding preview). */
  onSelect?: (key: string) => void;
  selected?: string;
  /** Hide the "Ändern? Sag es Henry." footer where the host says it already. */
  hideHint?: boolean;
  /** Draw the knob badge + the Henry track (harness-config-ui phase 4). Off by
   *  default so the onboarding preview - which shows the route to someone who
   *  has no repo yet and no knobs to count - keeps the plain row it wants. */
  showKnobs?: boolean;
}

/** How many of a station's knobs the app can actually EDIT, or null when the
 *  station is harness law.
 *
 *  Derived, never counted by hand: `settings` is the station's own declared key
 *  list and `editable` is the set the daemon really renders a control for, so
 *  the badge is their intersection. That is the same derivation loopmap's
 *  KnobChip already trusts - a knob named by a station but absent from the
 *  schema is exactly the case that once sent the owner to a screen which did
 *  not contain the knob it promised (routes_info.py's comment). */
function knobCount(node: LoopNode, editable?: string[]): number | null {
  if (node.kind === "fixed") return null;
  const named = node.settings ?? [];
  if (!named.length) return 0;
  if (!editable) return named.length;
  return named.filter((p) => editable.includes(p)).length;
}

/** The stations, in the daemon's order, with lanes/gate/deploy merged. */
export function useStations(map?: LoopMap | null): LoopNode[] {
  return useMemo(() => {
    const rt = map?.runtime;
    if (!rt) return [];
    const by: Record<string, LoopNode> = {};
    for (const l of rt.lanes ?? []) by[l.key] = l;
    if (rt.gate?.key) by[rt.gate.key] = rt.gate;
    if (rt.deploy?.key) by[rt.deploy.key] = rt.deploy;
    // `stations` is the server's draw order. Falling back to the lane order
    // keeps an older daemon rendering rather than blank.
    const order = rt.stations?.length ? rt.stations : (rt.lanes ?? []).map((l) => l.key);
    return order.map((k) => by[k]).filter(Boolean);
  }, [map]);
}

export function RepoPipeline({ map, onSelect, selected, hideHint, showKnobs }: PipelineProps) {
  const t = useTheme();
  const tr = useT();
  const stations = useStations(map);
  // The Henry band, indexed by station so the row below can line each segment
  // up under its own dot. No station list is built here - this only re-keys
  // what the daemon already aggregated.
  const henry = useMemo(() => {
    const by: Record<string, HenrySegment> = {};
    for (const seg of map?.runtime?.henry ?? []) by[seg.station] = seg;
    return by;
  }, [map]);
  const hasHenry = showKnobs && stations.some((s) => henry[s.key]);
  const repo: RepoView | null | undefined = map?.repo;
  // Everything the row could only hint at, collected for the list below it.
  const notes = stations
    .map((s) => ({
      key: s.key, label: s.label ?? s.key, off: s.active === false,
      text: s.active === false ? (s.off_reason || tr("pipeline.off")) : (s.note || ""),
    }))
    .filter((n) => !!n.text);
  if (!stations.length) return null;

  return (
    <View style={{ gap: 12 }}>
      <View style={{ flexDirection: "row", alignItems: "flex-start" }}>
        {stations.map((s, i) => {
          // `active` is only sent when a REPO was asked about. Undefined means
          // "the general machine" - everything on, nothing greyed.
          const off = s.active === false;
          const col = stationColor(t, s.key);
          const on = selected === s.key;
          return (
            <View key={s.key} style={{ flexDirection: "row", alignItems: "flex-start", flex: 1 }}>
              <Pressable
                testID={"station-" + s.key}
                onPress={onSelect ? () => onSelect(s.key) : undefined}
                disabled={!onSelect}
                style={{ alignItems: "center", gap: 5, flex: 1, paddingHorizontal: 2 }}>
                {s.key === "gate" ? <GateDot color={col} dim={off} /> : (
                  <View style={{ width: 30, height: 30, borderRadius: 15, alignItems: "center",
                    justifyContent: "center",
                    backgroundColor: off ? "transparent" : (on ? col : t.surface2),
                    borderWidth: off ? 1.5 : 2, borderColor: col,
                    // dashed, NOT hidden: the owner must see what he COULD have
                    borderStyle: off ? "dashed" : "solid" }}>
                    <View style={{ width: 10, height: 10, borderRadius: 5,
                      backgroundColor: off ? "transparent" : (on ? t.canvas : col) }} />
                  </View>
                )}
                {/* TWO lines, centred. On a 430px phone five stations get ~80px
                    each, and "Quality Gate" rendered as "Quality ..." - the one
                    station the owner is most likely to ask about, its name cut
                    off. Judged from the screenshot, not assumed. */}
                <Text numberOfLines={2} style={{ color: off ? t.txtTertiary : t.txtPrimary,
                  fontSize: 11, fontWeight: on ? "800" : "600", textAlign: "center" }}>
                  {s.label ?? s.key}
                </Text>
                {/* A TAG here, the sentence below. The full reason was rendered
                    under the dot first and the screenshot killed it: five
                    stations on a 430px phone leave ~80px each, so the honest
                    explanations came out as "Läuft leer - hier gibt es.." and
                    "Diese Vorlage benutzt die ...". A truncated reason is worse
                    than none - it looks like an answer and isn't one. */}
                {off ? (
                  <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 9.5 }}>
                    {tr("pipeline.off")}
                  </Text>
                ) : null}
                {/* THE KNOB BADGE (phase 4). A number when the station has
                    knobs, a padlock when it is law - never a toggle, because
                    exactly one station is switchable and four dummies would be
                    found out the first time one was tapped (sessions.py:240).
                    Suppressed on an off station: "3 Knöpfe" under a dashed dot
                    would advertise settings that do not run here. */}
                {showKnobs && !off ? (() => {
                  const n = knobCount(s, map?.editable);
                  if (n === null) {
                    return (
                      <Ionicons name="lock-closed" size={10} color={t.txtTertiary} />
                    );
                  }
                  return n > 0 ? (
                    <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 9.5,
                      fontWeight: "700" }}>
                      {tr("pipeline.knobs", { n })}
                    </Text>
                  ) : null;
                })() : null}
              </Pressable>
              {i < stations.length - 1 ? (
                <View style={{ width: 14, height: 2, marginTop: 14,
                  backgroundColor: t.borderStrong }} />
              ) : null}
            </View>
          );
        })}
      </View>

      {/* THE HENRY TRACK (design doc 5.4.3): a band under the row spanning the
          stations Henry acts at, with his verb per station. The segments arrive
          FINISHED from the daemon (behavior.track(), aggregated from the rules'
          `binds`), so adding a rule in the daemon lights a station here with no
          edit to this file - the dummy-knob test of the pipeline PRD, carried
          over to rules.

          A band, not a second set of edges: `edges` stays deliberately unread
          (see the header comment), and Henry's presence is not a route through
          the graph, it is a property OF stations. */}
      {hasHenry ? (
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <Text style={{ color: t.txtTertiary, fontSize: 10, fontWeight: "700",
            marginRight: 6 }}>
            {tr("pipeline.henry")}
          </Text>
          {stations.map((s, i) => {
            const seg = henry[s.key];
            return (
              <View key={s.key} style={{ flexDirection: "row", alignItems: "center", flex: 1 }}>
                <Pressable
                  testID={"henrytrack-" + s.key}
                  onPress={onSelect && seg ? () => onSelect(s.key) : undefined}
                  disabled={!onSelect || !seg}
                  style={{ flex: 1, paddingHorizontal: 2, alignItems: "center",
                    // A continuous rule under the stations he touches; a gap
                    // where he does not. The band IS the answer to "where does
                    // Henry act", so an unbroken line across everything would
                    // say the opposite of what it means.
                    borderTopWidth: seg ? 2 : 0, borderTopColor: t.accent2,
                    paddingTop: 3, minHeight: 16 }}>
                  {seg ? (
                    <Text numberOfLines={1} style={{ color: t.accent2, fontSize: 9.5,
                      fontWeight: "600" }}>
                      {tr(seg.labelKey)}
                    </Text>
                  ) : null}
                </Pressable>
                {i < stations.length - 1 ? <View style={{ width: 14 }} /> : null}
              </View>
            );
          })}
        </View>
      ) : null}

      {/* THE HONEST PART, given room to be read.
          Every station that is off, or on-but-not-what-you-think, gets one full
          sentence here. This is the difference the whole design turns on: "the
          gate is off" would be a lie in a document repo - it runs, finds nothing
          to compile, and reports PASS. Saying so takes a line of prose, and a
          line of prose does not fit under a 80px dot. */}
      {notes.length ? (
        <View style={{ gap: 6 }}>
          {notes.map((n) => (
            <View key={n.key} style={{ flexDirection: "row", gap: 7, alignItems: "flex-start" }}>
              <View style={{ width: 6, height: 6, borderRadius: 3, marginTop: 5,
                backgroundColor: n.off ? t.txtTertiary : stationColor(t, n.key) }} />
              <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16, flex: 1 }}>
                <Text style={{ fontWeight: "700" }}>{n.label}</Text>
                {" — " + n.text}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      {/* Deviations are DATA (projects.overrides / applied), recorded when the
          change happened - not a diff this screen computes. A silently
          overwritten value was the original complaint; this is the line that
          answers it. */}
      {repo?.deviations?.length ? (
        <View style={{ flexDirection: "row", gap: 8, backgroundColor: t.surface2,
          borderColor: t.warn, borderWidth: 1, borderRadius: 10, padding: 9 }}>
          <Ionicons name="alert-circle-outline" size={15} color={t.warn} style={{ marginTop: 1 }} />
          <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16, flex: 1 }}>
            {tr("pipeline.deviated", {
              keys: repo.deviations.map((d) => d.key).join(", "),
              template: repo.template_label || repo.template,
            })}
          </Text>
        </View>
      ) : null}

      {!hideHint ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
          <Ionicons name="chatbubble-ellipses-outline" size={14} color={t.txtTertiary} />
          <Text style={{ color: t.txtTertiary, fontSize: 11, flex: 1, lineHeight: 15.5 }}>
            {tr("pipeline.askHenry")}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
