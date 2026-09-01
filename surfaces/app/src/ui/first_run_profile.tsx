// The minimal profile step (accounts-boards-prd 4.2): ONE question, asked once,
// the first time an account signs in anywhere.
//
// Deliberately not a wizard. The PRD's line is "no wizard beyond that one step
// - personalization lives in Settings where it's discoverable when wanted", and
// the reason is G3: setup must END IN A WORKING BOARD, so every screen between
// the password and the board has to earn its place. Language earns it because
// it is the one preference that makes every OTHER screen readable; appearance
// does not, so it is not asked here.
//
// WHEN IT SHOWS: only while the account has not chosen a language -
// `me.profile_keys` excludes "lang". Not "is this a new account", not a
// first-run flag on the device: an account that picked German on a phone in
// March is not asked again on a laptop in September, because the question is
// about the ACCOUNT and the account has already answered. Conversely a legacy
// account that predates this feature IS asked once, on whichever device it
// next signs in on, which is exactly right.
//
// Skippable, and skipping writes nothing. An account with no `lang` row still
// renders in the workspace language (spine/storage/userconfig.py resolves it),
// so "skip" means "the workspace default is fine" - a real answer, not a
// deferred one. It reappears on the next sign-in because nothing was stored,
// which is the honest behaviour for a question that was never answered.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { create } from "zustand";

import { api } from "@/data/client";
import { useDemo } from "@/data/demo";
import { cacheProfile, migrateIfLegacy, saveProfile } from "@/data/profile";
import type { Me } from "@/data/types";
import { LANGS, useT, type Lang } from "@/i18n";
import { useTheme } from "@/theme";

// "Not now" for THIS app run only. Not persisted, on purpose: skipping stores
// nothing on the account, so the question is still unanswered - a device-side
// "don't ask again" would be a stored flag standing in for state the daemon
// actually owns, and the account would look decided when it is not.
const useSkipped = create<{ skipped: boolean; skip: () => void }>((set) => ({
  skipped: false,
  skip: () => set({ skipped: true }),
}));

/** Does the signed-in account still owe us a language, and has the device
 *  handed up whatever it was holding?
 *
 *  Both halves live here because they are ONE decision with an order: a legacy
 *  device must push its values up BEFORE we conclude the account never chose,
 *  or we would ask a question the device already had the answer to. The
 *  migration runs first, /me is refetched, and only then does `show` settle. */
export function useFirstRunProfile(): boolean {
  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const qc = useQueryClient();
  const skipped = useSkipped((s) => s.skipped);
  // The sample board has no account behind it (data/demo.ts answers /me from a
  // fixture), so there is nobody to ask and nowhere to store an answer -
  // asking would be a dead-end screen in the one mode meant to show the app
  // working immediately.
  const demo = useDemo((s) => s.active);
  // One attempt per signed-in account per app run. Keyed on the NAME so
  // switching accounts on a shared laptop re-arms it, and held in a ref rather
  // than state so a re-render mid-flight cannot fire a second push.
  const tried = useRef<string>("");
  const [settling, setSettling] = useState(false);

  // Write-through: whatever /me last resolved is what a cold start should
  // paint before the network answers.
  useEffect(() => { if (me?.profile) void cacheProfile(me.profile); }, [me?.profile]);

  useEffect(() => {
    if (demo || !me || tried.current === me.name) return;
    tried.current = me.name;
    if ((me.profile_keys?.length ?? 0) > 0) return;   // account already speaks
    setSettling(true);
    void migrateIfLegacy(me)
      .then((written) => (written.length ? qc.invalidateQueries({ queryKey: ["me"] }) : null))
      .finally(() => setSettling(false));
  }, [demo, me, qc]);

  if (demo || !me || skipped || settling) return false;
  return !(me.profile_keys ?? []).includes("lang");
}

/** Drops the minimal language step in front of the app while the account still
 *  owes an answer. Mounted INSIDE the QueryClientProvider (the hook reads /me),
 *  which is why this is a wrapper rather than another branch in _layout's
 *  gate chain - those run above the provider. */
export function ProfileGate({ children }: { children: React.ReactNode }) {
  return useFirstRunProfile() ? <FirstRunProfile /> : <>{children}</>;
}

export function FirstRunProfile() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  // Also called after a successful pick, not only on "skip": it settles the
  // screen on this frame instead of waiting for the /me refetch to land.
  const dismiss = useSkipped((s) => s.skip);
  const [busy, setBusy] = useState<Lang | null>(null);
  const [err, setErr] = useState("");

  async function pick(lang: Lang) {
    setBusy(lang); setErr("");
    try {
      await saveProfile({ lang });
      // /me carries the language every screen reads, so the whole tree has to
      // re-resolve before the board paints - otherwise the first frame after
      // this choice is still in the old language.
      await qc.invalidateQueries({ queryKey: ["me"] });
      dismiss();
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
      setBusy(null);
    }
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28 }}>
      <View style={{ width: "100%", maxWidth: 420, gap: 18 }}>
        <View style={{ gap: 8 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>
            {tr("profile.langTitle")}
          </Text>
          <Text style={{ color: t.txtSecondary, fontSize: 13.5, lineHeight: 19 }}>
            {tr("profile.langHint")}
          </Text>
        </View>

        <View style={{ gap: 10 }}>
          {LANGS.map((l) => (
            <Pressable key={l.id} onPress={() => pick(l.id as Lang)} disabled={!!busy}
              style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
                backgroundColor: busy === l.id ? t.surface2 : t.accent, borderRadius: 14,
                paddingVertical: 14, opacity: busy && busy !== l.id ? 0.5 : 1 }}>
              {busy === l.id ? <ActivityIndicator color="#fff" /> : null}
              <Text style={{ color: busy === l.id ? t.txtSecondary : "#fff", fontSize: 15, fontWeight: "600" }}>
                {l.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {err ? <Text style={{ color: t.danger, fontSize: 12.5 }}>{err}</Text> : null}

        <Pressable onPress={dismiss} disabled={!!busy} style={{ alignItems: "center", paddingVertical: 6 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 13, fontWeight: "600" }}>
            {tr("profile.langSkip")}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}
