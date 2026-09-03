import { Ionicons } from "@expo/vector-icons";
import { Animated as RNAnimated, Easing, Pressable, Text, View } from "react-native";
import { useEffect, useMemo, useRef } from "react";

import type { CellTrack, LoopMap, LoopNode, RepoView } from "@/data/client";
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
function GateDot({ color, dim, size = 30 }: { color: string; dim: boolean; size?: number }) {
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
        <RNAnimated.View style={{ position: "absolute", width: size, height: size,
          borderRadius: size / 2,
          borderWidth: 2, borderColor: color, transform: [{ scale }], opacity: op }} />
      ) : null}
      <View style={{ width: size, height: size, borderRadius: size / 2, alignItems: "center",
        justifyContent: "center", backgroundColor: dim ? "transparent" : color,
        borderWidth: dim ? 1.5 : 0, borderColor: color,
        borderStyle: dim ? "dashed" : "solid" }}>
        <Ionicons name="shield-checkmark" size={size * 0.53} color={dim ? color : "#fff"} />
      </View>
    </View>
  );
}

/** A STEP, drawn ON the connector it runs in - deliberately smaller than a lane
 *  dot and sitting on the line rather than beside it.
 *
 *  The size difference is the whole point of the fix. The gate is not a place a
 *  card waits, it is what happens on the way from "In Arbeit" to "Abnahme";
 *  deploy is what happens after the accept. Rendered as equal columns they read
 *  as lanes the owner should be able to find on his board - and he cannot,
 *  because they are not there. Same dot, half the size, on the edge: the
 *  picture now says "inside this transition". */
function StepMarker({ step, onSelect, selected }: {
  step: LoopNode; onSelect?: (k: string) => void; selected?: string;
}) {
  const t = useTheme();
  const off = step.active === false;
  const col = stationColor(t, step.key);
  const on = selected === step.key;
  return (
    <Pressable
      testID={"station-" + step.key}
      onPress={onSelect ? () => onSelect(step.key) : undefined}
      disabled={!onSelect}
      style={{ alignItems: "center", width: STEP_W }}>
      {/* A ring in the canvas colour so the connector does not run through the
          glyph - the line has to READ as passing behind the step. */}
      <View style={{ borderRadius: 13, padding: 2, backgroundColor: t.canvas }}>
        {step.key === "gate" ? <GateDot color={col} dim={off} size={STEP_DOT} /> : (
          <View style={{ width: STEP_DOT, height: STEP_DOT, borderRadius: STEP_DOT / 2,
            alignItems: "center", justifyContent: "center",
            backgroundColor: off ? "transparent" : (on ? col : t.surface2),
            borderWidth: off ? 1.5 : 2, borderColor: col,
            borderStyle: off ? "dashed" : "solid" }}>
            <Ionicons name={step.key === "deploy" ? "rocket" : "ellipse"}
              size={STEP_DOT * 0.5} color={off ? col : (on ? t.canvas : col)} />
          </View>
        )}
      </View>
    </Pressable>
  );
}

// ONE geometry, used by the station row AND by the Henry band under it, so the
// band cannot drift out of alignment with the dots it annotates.
//
// STEP_W IS A BUDGET, and a measured one. The step marker carried its name
// under the dot at first, which needed 52px of gap - and on a 430px phone that
// took the lane columns down to 41px, clipping Henry's "nimmt ab" and making
// the steps WIDER than the lanes they are subordinate to. Inverting the
// hierarchy is the same lie as the five-column row, just drawn differently. So
// the marker keeps only its glyph here and its name moved to the legend below,
// where it has a full line to be read on.
const STEP_DOT = 22;
const STEP_W = 26;
const PLAIN_W = 14;

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
  /** {station: knob count}, from the SCHEMA's own `station` tags
   *  (harness-config-ui section 6). Pass it wherever the station PAGES are
   *  rendered too, so the badge on the row and the count in the navigation are
   *  ONE derivation.
   *
   *  Without it the badge falls back to `node.settings` - a list kept by hand
   *  in sessions.LANE_FLOW, which went out of step with the schema the moment
   *  knobs started carrying `station`: the row read "2 Knöpfe" under a station
   *  whose page rendered three. Two honest derivations contradicting each other
   *  on one screen is worse than either being slightly wrong. */
  knobsAt?: Record<string, number>;
}

/** How many of a station's knobs the app can actually EDIT, or null when the
 *  station is harness law.
 *
 *  Derived, never counted by hand. `knobsAt` (the schema's station tags) is the
 *  authority where the caller has it; otherwise the badge falls back to the
 *  intersection of the station's declared `settings` and the `editable` set -
 *  the derivation loopmap's KnobChip already trusts, and the right answer for a
 *  host like repo onboarding that holds no schema. */
function knobCount(node: LoopNode, editable?: string[],
                   knobsAt?: Record<string, number>): number | null {
  if (node.kind === "fixed") return null;
  if (knobsAt) return knobsAt[node.key] ?? 0;
  const named = node.settings ?? [];
  if (!named.length) return 0;
  if (!editable) return named.length;
  return named.filter((p) => editable.includes(p)).length;
}

/** A step (gate/deploy) riding the connector that LEAVES lane `afterIdx`. */
export interface PipelineStep { node: LoopNode; afterIdx: number }
export interface PipelineRow { lanes: LoopNode[]; steps: PipelineStep[] }

/** The row to draw: the real lanes as columns, gate/deploy as steps on the
 *  connectors between them.
 *
 *  THE COLUMNS ARE THE LANES, and nothing else. This used to render
 *  `runtime.stations` - a flat five-name vocabulary - as five equal columns,
 *  which drew "Quality Gate" and "Deploy" ranking with the lanes and left the
 *  owner's fourth lane ("Fertig") off the screen entirely. The board said four,
 *  the map said five. Count and names now come from `row.lanes`, i.e. from the
 *  same nodes policy.lane_labels renames, so renaming a lane or adding one
 *  changes this row with no edit here. */
export function useRow(map?: LoopMap | null): PipelineRow {
  return useMemo(() => {
    const rt = map?.runtime;
    if (!rt) return { lanes: [], steps: [] };
    const by: Record<string, LoopNode> = {};
    for (const l of rt.lanes ?? []) by[l.key] = l;
    if (rt.gate?.key) by[rt.gate.key] = rt.gate;
    if (rt.deploy?.key) by[rt.deploy.key] = rt.deploy;
    // An older daemon sends no `row`; then the lanes ARE the row and the steps
    // are simply not placed. A plain lane row is still a true picture - the
    // five-column one was not.
    const keys = rt.row?.lanes?.length ? rt.row.lanes : (rt.lanes ?? []).map((l) => l.key);
    const lanes = keys.map((k) => by[k]).filter(Boolean);
    const steps: PipelineStep[] = [];
    for (const s of rt.row?.steps ?? []) {
      const node = by[s.key];
      if (!node) continue;
      const afterIdx = keys.indexOf(s.after);
      // Placed by KEY on the server, resolved to a position here. An unplaceable
      // step still gets drawn, on the last connector, rather than disappearing.
      steps.push({ node, afterIdx: afterIdx >= 0 ? afterIdx : lanes.length - 1 });
    }
    return { lanes, steps };
  }, [map]);
}

export function RepoPipeline({ map, onSelect, selected, hideHint, showKnobs, knobsAt }: PipelineProps) {
  const t = useTheme();
  const tr = useT();
  const { lanes: stations, steps } = useRow(map);
  // Which connector carries which step, and therefore how wide each gap is.
  // Read by both rows below - the band under the dots has to use the SAME
  // widths or Henry's segments end up annotating the wrong station.
  const stepAt = useMemo(() => {
    const by: Record<number, LoopNode> = {};
    for (const s of steps) by[s.afterIdx] = s.node;
    return by;
  }, [steps]);
  // The connector GROWS with the row instead of staying a 14px stub. On a
  // desktop-width card a fixed stub left the dots floating unconnected, which
  // undoes the whole point of putting the steps ON the line - a step has to be
  // seen sitting IN a transition. minWidth keeps the step's own glyph from ever
  // being squeezed on a phone; the flex share stays well under a lane's 1 so a
  // connector can never out-measure the lanes it joins.
  const gapStyle = (i: number) => ({
    flex: stepAt[i] ? 0.5 : 0.3, minWidth: stepAt[i] ? STEP_W : PLAIN_W,
  });
  // THE CELL TRACKS, one band per acting agent - the generalisation of the
  // Henry band (owner directive 2026-09-03: "Henry steuert, Engineer baut"
  // has to be readable as a picture). Each track arrives FINISHED from the
  // daemon (apimeta._cell_tracks: copilot derived from its rules' binds,
  // every other cell from its declared board metadata in the registry) and is
  // only re-keyed by station here. An older daemon sends `henry` alone; that
  // degrades to the one band this row always had.
  const tracks = useMemo(() => {
    const raw: CellTrack[] = map?.runtime?.cells?.length
      ? map.runtime.cells
      : (map?.runtime?.henry?.length
          ? [{ cell: "copilot", label: "Henry",
               segments: (map.runtime.henry ?? []).map((s) => ({
                 station: s.station, labelKeys: [s.labelKey] })) }]
          : []);
    return raw.map((tk) => {
      const by: Record<string, { station: string; labelKeys: string[] }> = {};
      for (const seg of tk.segments) by[seg.station] = seg;
      return { ...tk, by };
    });
  }, [map]);
  // gate/deploy are STEPS riding a connector, not entries in `stations` (the
  // LANE list) - a track whose only segment sits on a step (e.g. engineer's
  // "prüft"/"liefert aus") would otherwise never be found by a lane-only
  // lookup and silently vanish from the picture. Checked here once, reused by
  // both the visibility gate and the per-track filter below.
  const stepKeys = Object.values(stepAt).map((n) => n.key);
  const hasTracks = showKnobs && tracks.some((tk) =>
    stations.some((s) => tk.by[s.key]) || stepKeys.some((k) => tk.by[k]));
  // One colour per band, stable by CELL rather than by position, so Henry is
  // always his accent2 whatever order the registry lists the cells in. An
  // unknown cell falls back to a palette slot by index.
  const namedTrackColor: Record<string, string> = {
    copilot: t.accent2, engineer: t.human, pm: t.accent,
  };
  const palette = [t.ok, t.warn, t.accent2, t.human];
  const trackColor = (cell: string, i: number) =>
    namedTrackColor[cell] ?? palette[i % palette.length];
  const repo: RepoView | null | undefined = map?.repo;
  // Everything the row could only hint at, collected for the list below it.
  // Lanes AND steps: the sentence explaining why deploy is dark is exactly the
  // one the owner needs, and the step's caption is far too small to carry it.
  const notes = [...stations, ...steps.map((s) => s.node)]
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
                {/* TWO lines, centred. The old five-column row left ~80px per
                    station on a 430px phone and cut "Quality Gate" to
                    "Quality ..."; moving the two steps onto the connectors buys
                    the real lanes their width back. */}
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
                  const n = knobCount(s, map?.editable, knobsAt);
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
              {/* THE CONNECTOR, which is also where the steps live. The line is
                  drawn absolutely across the full gap and the step sits on top
                  of it, so gate/deploy read as something happening ON the way
                  from one lane to the next - not as a lane. */}
              {i < stations.length - 1 ? (
                <View style={{ ...gapStyle(i), alignItems: "center" }}>
                  <View style={{ position: "absolute", left: 0, right: 0, top: 14, height: 2,
                    backgroundColor: t.borderStrong }} />
                  {stepAt[i] ? (
                    <StepMarker step={stepAt[i]} onSelect={onSelect} selected={selected} />
                  ) : null}
                </View>
              ) : null}
            </View>
          );
        })}
      </View>

      {/* THE STEP LEGEND: what the two markers on the connectors ARE, and -
          said in words, not only by position - that each happens INSIDE a lane
          transition. The card this fixes was filed because the row implied the
          opposite: an owner reading "Quality Gate" as a column went looking for
          that lane on his board and it does not exist. A glyph on an edge is
          the picture; this line is the sentence, and the owner gets both. */}
      {steps.length ? (
        <View style={{ gap: 5 }}>
          {steps.map(({ node, afterIdx }) => {
            const off = node.active === false;
            const col = stationColor(t, node.key);
            // The transition it runs in, named with the lanes' CURRENT labels -
            // the same ones the row above drew, so a rename cannot leave this
            // sentence talking about a lane the owner no longer has.
            const from = stations[afterIdx];
            const to = stations[afterIdx + 1];
            return (
              <View key={node.key}
                style={{ flexDirection: "row", gap: 7, alignItems: "center" }}>
                <Ionicons name={node.key === "gate" ? "shield-checkmark" : "rocket"}
                  size={11} color={off ? t.txtTertiary : col} />
                <Text numberOfLines={2} style={{ color: t.txtSecondary, fontSize: 11,
                  lineHeight: 15, flex: 1 }}>
                  <Text style={{ fontWeight: "700", color: off ? t.txtTertiary : t.txtPrimary }}>
                    {node.label ?? node.key}
                  </Text>
                  {from && to ? " — " + tr("pipeline.stepOn", {
                    from: from.label ?? from.key, to: to.label ?? to.key,
                  }) : ""}
                </Text>
              </View>
            );
          })}
        </View>
      ) : null}

      {/* THE CELL TRACKS (design doc 5.4.3, generalised): one band per acting
          agent under the station row - who does WHAT and WHERE, as a picture.
          "Henry steuert, engineer baut" is readable without a word of prose:
          each band spans the stations its cell acts at, with its verb per
          station. The segments arrive FINISHED from the daemon, so adding a
          rule (copilot) or a board declaration (any other cell) lights a
          station here with no edit to this file - the dummy-knob test of the
          pipeline PRD, carried over to cells.

          Bands, not a second set of edges: `edges` stays deliberately unread
          (see the header comment), and a cell's presence is not a route
          through the graph, it is a property OF stations. */}
      {hasTracks ? (
        <View style={{ gap: 3 }}>
          {tracks.map((tk, ti) => {
            if (!stations.some((s) => tk.by[s.key]) && !stepKeys.some((k) => tk.by[k])) return null;
            const col = trackColor(tk.cell, ti);
            return (
              <View key={tk.cell} style={{ flexDirection: "row", alignItems: "center" }}>
                {/* A FIXED label column, shared by every band, so the bands'
                    segments line up with each other - a label as wide as its
                    text would slide each band by a different offset. */}
                <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 10,
                  fontWeight: "700", width: 58 }}>
                  {tk.label}
                </Text>
                {stations.map((s, i) => {
                  const seg = tk.by[s.key];
                  // gate/deploy ride the CONNECTOR after this lane, same as
                  // StepMarker above - a step's verb has no lane of its own to
                  // sit under, so it renders IN the gap, not in the next lane's
                  // column (which would misattribute it to that lane).
                  const step = stepAt[i];
                  const stepSeg = step ? tk.by[step.key] : undefined;
                  return (
                    <View key={s.key} style={{ flexDirection: "row", alignItems: "center", flex: 1 }}>
                      <Pressable
                        // The copilot band keeps the testID contract the Henry
                        // band shipped with (e2e_pipeline_track.py reads it).
                        testID={(tk.cell === "copilot" ? "henrytrack-"
                          : "track-" + tk.cell + "-") + s.key}
                        onPress={onSelect && seg ? () => onSelect(s.key) : undefined}
                        disabled={!onSelect || !seg}
                        style={{ flex: 1, paddingHorizontal: 2, alignItems: "center",
                          // A continuous rule under the stations this agent
                          // touches; a gap where it does not. The band IS the
                          // answer to "where does this agent act", so an
                          // unbroken line across everything would say the
                          // opposite of what it means.
                          borderTopWidth: seg ? 2 : 0, borderTopColor: col,
                          paddingTop: 3, minHeight: 16 }}>
                        {seg ? (
                          <Text numberOfLines={1} style={{ color: col, fontSize: 9.5,
                            fontWeight: "600" }}>
                            {seg.labelKeys.map((k) => tr(k)).join(" · ")}
                          </Text>
                        ) : null}
                      </Pressable>
                      {/* The SAME gap geometry as the row above - see gapStyle.
                          Any divergence here slides the verbs off their
                          stations. A step's verb (engineer's "prüft"/"liefert
                          aus") sits centred in this same gap, so it is never
                          silently dropped for having no lane of its own. */}
                      {i < stations.length - 1 ? (
                        <Pressable
                          testID={step ? (tk.cell === "copilot" ? "henrytrack-"
                            : "track-" + tk.cell + "-") + step.key : undefined}
                          onPress={onSelect && stepSeg ? () => onSelect(step!.key) : undefined}
                          disabled={!onSelect || !stepSeg}
                          style={{ ...gapStyle(i), alignItems: "center",
                            borderTopWidth: stepSeg ? 2 : 0, borderTopColor: col,
                            paddingTop: stepSeg ? 3 : 0, minHeight: stepSeg ? 16 : undefined }}>
                          {stepSeg ? (
                            <Text numberOfLines={1} style={{ color: col, fontSize: 9,
                              fontWeight: "600" }}>
                              {stepSeg.labelKeys.map((k) => tr(k)).join(" · ")}
                            </Text>
                          ) : null}
                        </Pressable>
                      ) : null}
                    </View>
                  );
                })}
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
