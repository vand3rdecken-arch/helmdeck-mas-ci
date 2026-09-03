import type { ReactNode } from "react";
import { Platform, Text, View } from "react-native";

import type { StoredConfig, StoredProjectRow } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Hint } from "@/ui/settings_sections";

/**
 * WHAT IS ACTUALLY IN THE STORE.
 *
 * Every other config surface in the app answers the RESOLVED question - which
 * value applies here, and which layer did it come from. That is the right
 * question for changing a setting and the wrong one for auditing it, because a
 * resolved answer cannot tell "nothing was ever set" apart from "a row exists
 * and something above it wins". This panel answers the other one: which rows
 * physically exist, in which table, for which scope.
 *
 * It RESOLVES NOTHING. Every field here is rendered exactly as
 * spine/storage/configreview.py returned it - no fallbacks applied, no empty
 * label swapped for a station name, no inheritance folded in. That is the whole
 * value of the view: the moment it starts being helpful about missing values it
 * stops being able to prove anything, and the scope badges elsewhere in the app
 * go back to being taken on trust.
 *
 * THE TWO ROWS NOTHING ELSE CAN SHOW, and why they earn a screen:
 *   - a row for a project you are NOT looking at. The harness screen resolves
 *     one project at a time, so a value set months ago against another repo is
 *     invisible there by construction.
 *   - an UNDECLARED row. A retired knob leaves its value on disk and the daemon
 *     stops honouring it. That is not garbage - it is something the owner set
 *     that silently went inert - so it is shown with a warning rather than
 *     filtered out, which is what the resolved view does with it.
 */

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

type Tr = (k: string, p?: Record<string, string | number>) => string;

/** A value as stored, not as rendered. Objects and arrays are JSON so a labels
 *  map is readable as the one value it is; long prose is clipped with an
 *  explicit ellipsis rather than silently, because "this is longer than shown"
 *  is itself part of the audit. */
function asStored(v: unknown): string {
  if (v === null || v === undefined) return "null";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > 400 ? s.slice(0, 400) + " …" : s;
}

function Row({ children, t }: { children: ReactNode; t: ThemeTokens }) {
  return (
    <View style={{ gap: 3, paddingVertical: 7, borderTopWidth: 1, borderTopColor: t.glassBorder }}>
      {children}
    </View>
  );
}

function Tag({ text, tone, t }: { text: string; tone: "accent" | "warn" | "muted"; t: ThemeTokens }) {
  const color = tone === "accent" ? t.accent : tone === "warn" ? t.danger : t.txtTertiary;
  return (
    <View style={{ borderWidth: 1, borderRadius: 5, paddingHorizontal: 5, paddingVertical: 1,
      borderColor: tone === "muted" ? t.borderSubtle : color, backgroundColor: t.surface2 }}>
      <Text style={{ color, fontSize: 9.5, fontWeight: "600" }}>{text}</Text>
    </View>
  );
}

function Section({ title, count, children, t }: {
  title: string; count: number; children: ReactNode; t: ThemeTokens;
}) {
  return (
    <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
      borderRadius: 14, padding: 14, gap: 2 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap",
        paddingBottom: 4 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 14.5, fontWeight: "700", flexShrink: 1 }}>
          {title}
        </Text>
        <Tag text={String(count)} tone="muted" t={t} />
      </View>
      {children}
    </View>
  );
}

function ProjectRow({ r, t, tr }: { r: StoredProjectRow; t: ThemeTokens; tr: Tr }) {
  return (
    <Row t={t}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
        <Text selectable style={{ color: t.txtPrimary, fontSize: 11.5, fontFamily: MONO, flexShrink: 1 }}>
          {r.key}
        </Text>
        {r.selected ? <Tag text={tr("stored.thisProject")} tone="accent" t={t} /> : null}
        {!r.declared ? <Tag text={tr("stored.undeclared")} tone="warn" t={t} /> : null}
      </View>
      <Text selectable style={{ color: t.txtSecondary, fontSize: 11, fontFamily: MONO }}>
        {asStored(r.value)}
      </Text>
      <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
        {tr("stored.forProject", { project: r.project || tr("stored.workspaceKey") })}
      </Text>
      {/* The reason an undeclared row is worth a sentence rather than a badge:
          it does not look broken from anywhere else in the app. */}
      {!r.declared ? <Hint text={tr("stored.undeclared.desc")} /> : null}
    </Row>
  );
}

/** The panel. `stored` absent means a daemon that predates this block - said
 *  plainly rather than drawn as three empty sections, which would read as "the
 *  store is empty" and is the opposite of the truth. */
export function StoredConfigPanel({ stored }: { stored?: StoredConfig }) {
  const t = useTheme();
  const tr = useT() as Tr;

  if (!stored) {
    return (
      <Section title={tr("stored.title")} count={0} t={t}>
        <Hint text={tr("stored.unavailable")} />
      </Section>
    );
  }

  const { projectRows, boardRows, legacyRows } = stored;

  return (
    <View style={{ gap: 14 }}>
      <Section title={tr("stored.title")} count={projectRows.length} t={t}>
        <Hint text={tr("stored.intro")} />
        {projectRows.length === 0 ? (
          <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16.5, paddingTop: 6 }}>
            {tr("stored.noProjectRows")}
          </Text>
        ) : projectRows.map((r) => (
          <ProjectRow key={r.project + "|" + r.key} r={r} t={t} tr={tr} />
        ))}
      </Section>

      {/* THE BOARD SCOPE'S REAL STORE. The hub badges a knob "Board"; this is
          what that badge points at, in the table it actually lives in. An empty
          label is shown as empty - that is a column deliberately left to render
          its station's own name, and resolving it here would hide the
          difference between "unset" and "set to the station name". */}
      <Section title={tr("stored.boards")} count={boardRows.length} t={t}>
        <Hint text={tr("stored.boards.intro")} />
        {boardRows.map((b) => (
          <Row key={b.id} t={t}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
              <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600", flexShrink: 1 }}>
                {b.name}
              </Text>
              <Tag text={b.owner === "" ? tr("stored.shared") : b.owner} tone="muted" t={t} />
            </View>
            {b.columns.map((c, i) => (
              <View key={b.id + "|" + i} style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                <Text selectable style={{ color: t.txtTertiary, fontSize: 11, fontFamily: MONO,
                  width: 74 }}>
                  {c.station}
                </Text>
                <Text selectable style={{ fontSize: 11, fontFamily: MONO, flexShrink: 1,
                  color: c.label ? t.txtSecondary : t.txtTertiary,
                  fontStyle: c.label ? "normal" : "italic" }}>
                  {c.label || tr("stored.emptyLabel")}
                </Text>
              </View>
            ))}
          </Row>
        ))}
      </Section>

      {/* Normally empty, and that is the healthy state. A row here means either
          the daemon has not restarted since the rules shipped, or a legacy value
          failed its own rule's validator and is being KEPT rather than dropped -
          both of which are things you want to be told, not to discover. */}
      {legacyRows.length ? (
        <Section title={tr("stored.legacy")} count={legacyRows.length} t={t}>
          <Hint text={tr("stored.legacy.intro")} />
          {legacyRows.map((l) => (
            <Row key={l.key} t={t}>
              <Text selectable style={{ color: t.txtPrimary, fontSize: 11.5, fontFamily: MONO }}>
                {l.key} → {l.path}
              </Text>
              {l.refuse ? (
                <View style={{ flexDirection: "row", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                  <Tag text={tr("stored.refused")} tone="warn" t={t} />
                  <Text style={{ color: t.txtSecondary, fontSize: 11, flexShrink: 1 }}>{l.refuse}</Text>
                </View>
              ) : (
                <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("stored.legacy.pending")}</Text>
              )}
            </Row>
          ))}
        </Section>
      ) : null}
    </View>
  );
}
