import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { api, type RepoTemplates, type RepoView } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

import { getFolderPicker } from "./folder_picker";

/**
 * THE repo-type question - one component, rendered in two places.
 *
 * It used to live inline in app/repo.tsx, whose docstring calls that screen
 * "the ONE place a repo's type is chosen". First-run onboarding needs to ask
 * the same question (a new user with no repo would otherwise land on an empty
 * board and never meet the choice at all), and the honest way to do that is to
 * render the SAME component - not to grow a second, drifting copy.
 *
 * That is the precedent onboard.tsx already set for sign-in: it renders
 * LoginScreen rather than restating it, because two sign-in surfaces would be
 * the same mistake as maintaining two chat UIs. Same rule here.
 *
 * Self-contained on purpose: it runs its own /repo/templates query (react-query
 * dedupes it against the other screen's by key, so mounting both costs one
 * request) and reports the selected repo upward for whatever the host wants to
 * draw next - the pipeline preview on the settings screen, the continue button
 * during onboarding.
 */
export function RepoTypePicker({
  onRepoChange, wide = false, intro,
}: {
  /** The host is told which repo is selected - it does not own the state. */
  onRepoChange?: (repo: string) => void;
  /** Lay the two type cards side by side (desktop/tablet) instead of stacked. */
  wide?: boolean;
  /** Replace the default lead-in line; onboarding phrases it as a first step. */
  intro?: string;
}) {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery<RepoTemplates>({
    queryKey: ["repoTemplates"], queryFn: api.repoTemplates,
  });
  const [repo, setRepoState] = useState("");
  const [err, setErr] = useState("");

  const setRepo = (v: string) => { setRepoState(v); onRepoChange?.(v); };

  // Desktop-only (Electron preload bridge, see folder_picker.ts) - null on
  // phone/web/Mac, where the free-text field stays the only way in.
  const folderPicker = getFolderPicker();

  // Land on the repo that still needs a decision. A repo with no type is the
  // only thing here that is actually outstanding, so preferring it over "the
  // first one" means the screen opens on the work.
  useEffect(() => {
    if (repo || !data?.repos?.length) return;
    setRepo((data.repos.find((r) => !r.template) ?? data.repos[0]).repo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, repo]);

  const current: RepoView | undefined = data?.repos.find((r) => r.repo === repo);

  const apply = useMutation({
    mutationFn: (template: string) => api.applyRepoTemplate(repo, template),
    onSuccess: (r) => {
      if (r?.error) { setErr(r.error); return; }
      setErr("");
      // Both queries, because both are now stale: the record changed AND the
      // pipeline it produces changed.
      qc.invalidateQueries({ queryKey: ["repoTemplates"] });
      qc.invalidateQueries({ queryKey: ["loopmap"] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  if (isLoading) return <ActivityIndicator color={t.accent} style={{ marginTop: 24 }} />;
  if (error || !data) {
    return <Text style={{ color: t.danger, padding: 16 }}>{tr("health.unreachable")}</Text>;
  }

  return (
    <View style={{ gap: 16 }}>
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 18 }}>
        {intro ?? tr("repo.intro")}
      </Text>

      {/* ---- which repo ---- */}
      <View style={{ gap: 8 }}>
        <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", letterSpacing: 0.6 }}>
          {tr("repo.which").toUpperCase()}
        </Text>
        {data.repos.length ? (
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
            {data.repos.map((r) => {
              const on = r.repo === repo;
              return (
                // testID by NAME, not by path: a Windows path is full of
                // backslashes, and `[data-testid="C:\Users\..."]` reads \U
                // as a CSS escape - the shot driver matched 0 nodes and the
                // screenshots silently showed an unclicked screen.
                <Pressable key={r.repo} testID={"repo-" + (r.project?.name || r.repo)}
                  onPress={() => { setRepo(r.repo); setErr(""); }}
                  style={{ flexDirection: "row", alignItems: "center", gap: 6,
                    backgroundColor: on ? t.accent : t.surface1,
                    borderColor: r.template ? t.glassBorder : t.warn, borderWidth: 1,
                    borderRadius: 999, paddingHorizontal: 11, paddingVertical: 7 }}>
                  <Text numberOfLines={1} style={{ color: on ? t.canvas : t.txtPrimary,
                    fontSize: 12, fontWeight: on ? "800" : "600", maxWidth: 260 }}>
                    {r.project?.name || r.repo}
                  </Text>
                  {/* a repo with no type is the outstanding decision - mark it */}
                  {!r.template ? (
                    <View style={{ backgroundColor: t.warn, borderRadius: 999, paddingHorizontal: 6, paddingVertical: 1 }}>
                      <Text style={{ color: t.canvas, fontSize: 9, fontWeight: "800" }}>{tr("repo.noType")}</Text>
                    </View>
                  ) : null}
                </Pressable>
              );
            })}
          </View>
        ) : (
          <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("repo.none")}</Text>
        )}
        <View style={{ flexDirection: "row", gap: 8 }}>
          <TextInput value={repo} onChangeText={(v) => { setRepo(v); setErr(""); }}
            autoCapitalize="none" autoCorrect={false} placeholder={tr("repo.pathPlaceholder")}
            placeholderTextColor={t.txtTertiary}
            style={{ flex: 1, backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
              borderRadius: 10, paddingHorizontal: 11, paddingVertical: 9, color: t.txtPrimary, fontSize: 12.5 }} />
          {folderPicker ? (
            <Pressable testID="repo-pick-folder" accessibilityLabel={tr("repo.chooseFolder")}
              onPress={async () => {
                const picked = await folderPicker();
                if (picked) { setRepo(picked); setErr(""); }
              }}
              style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
                borderRadius: 10, paddingHorizontal: 11, justifyContent: "center", alignItems: "center" }}>
              <Ionicons name="folder-open-outline" size={18} color={t.txtPrimary} />
            </Pressable>
          ) : null}
        </View>
      </View>

      {/* ---- the one question ---- */}
      <View style={{ gap: 8 }}>
        <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", letterSpacing: 0.6 }}>
          {tr("repo.pickType").toUpperCase()}
        </Text>
        <View style={{ flexDirection: wide ? "row" : "column", gap: 10 }}>
          {data.templates.map((tpl) => {
            const on = current?.template === tpl.id;
            return (
              <Pressable key={tpl.id} testID={"tpl-" + tpl.id}
                disabled={!repo || apply.isPending}
                onPress={() => apply.mutate(tpl.id)}
                style={{ flex: wide ? 1 : undefined, backgroundColor: t.surface1,
                  borderColor: on ? t.accent : t.glassBorder, borderWidth: on ? 2 : 1,
                  borderRadius: 14, padding: 13, gap: 6, opacity: repo ? 1 : 0.5 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
                  <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "700", flex: 1 }}>
                    {tpl.label}
                  </Text>
                  {on ? <Ionicons name="checkmark-circle" size={18} color={t.accent} /> : null}
                </View>
                <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16 }}>{tpl.who}</Text>
                {/* `summary`, NOT `body`. The first build rendered the whole
                    markdown file here - asterisks, backticks and all - and
                    the screenshot settled it: the pipeline, which is the
                    entire point of that screen, ended up three screens
                    below the fold. The file's prose is for whoever edits
                    the template; the owner picking a type needs one line
                    and then the picture. */}
                <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 15.5 }}>
                  {tpl.summary}
                </Text>
              </Pressable>
            );
          })}
        </View>
        {apply.isPending ? <ActivityIndicator color={t.accent} /> : null}
        {err ? <Text style={{ color: t.danger, fontSize: 12 }}>{err}</Text> : null}
      </View>
    </View>
  );
}

/** Whether any repo still has no type. Onboarding asks this to decide if the
 *  repo step is worth showing at all - a returning user who already chose must
 *  not be walked through it again. `undefined` = not answered yet, which the
 *  caller should treat as "show nothing", not as "nothing to do". */
export function useRepoTypeOutstanding(): boolean | undefined {
  const { data } = useQuery<RepoTemplates>({
    queryKey: ["repoTemplates"], queryFn: api.repoTemplates,
  });
  if (!data) return undefined;
  return !data.repos.length || data.repos.some((r) => !r.template);
}
