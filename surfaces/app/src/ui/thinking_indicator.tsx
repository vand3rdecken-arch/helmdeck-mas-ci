import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import { Animated, Text, View } from "react-native";
import { isWeb } from "@/ui/responsive";
import { webMotion } from "@/ui/web_motion";

import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// A live "thinking" row while Henry works: pulsing dots + an elapsed clock (like
// Claude), so the wait reads as active reasoning, not a frozen "denkt". ONE row
// for every Henry thread - the board chat and the team rooms both draw it (owner
// 2026-10-10: a room's Henry must look like the chat's Henry).
export function ThinkingIndicator({ preview, since }: { preview?: string; since?: number | null }) {
  const t = useTheme();
  const tr = useT();
  const d0 = useRef(new Animated.Value(0.25)).current;
  const d1 = useRef(new Animated.Value(0.25)).current;
  const d2 = useRef(new Animated.Value(0.25)).current;
  // ELAPSED FROM THE DAEMON'S CLOCK when it says when the turn began: a
  // local setInterval restarts at 0 on every remount and stops while the app
  // is backgrounded, so "denkt nach · 24s" was showing for a turn that had
  // been running three minutes (owner 2026-09-14 12:38). Falls back to the
  // local counter against an older daemon that sends no `since`.
  const [secs, setSecs] = useState(() => since ? Math.max(0, Math.floor(Date.now() / 1000 - since)) : 0);
  useEffect(() => {
    if (!since) return;
    setSecs(Math.max(0, Math.floor(Date.now() / 1000 - since)));
  }, [since]);
  useEffect(() => {
    const pulse = (v: Animated.Value, delay: number) =>
      Animated.loop(Animated.sequence([
        Animated.delay(delay),
        Animated.timing(v, { toValue: 1, duration: 300, useNativeDriver: true }),
        Animated.timing(v, { toValue: 0.25, duration: 300, useNativeDriver: true }),
        Animated.delay(360 - delay),
      ]));
    // web: webMotion.dot (CSS) - an Animated loop here re-renders 60x/s from JS
    const anims = isWeb ? [] : [pulse(d0, 0), pulse(d1, 160), pulse(d2, 320)];
    anims.forEach((a) => a.start());
    const iv = setInterval(() => setSecs((s) => (since ? Math.max(0, Math.floor(Date.now() / 1000 - since)) : s + 1)), 1000);
    return () => { anims.forEach((a) => a.stop()); clearInterval(iv); };
  }, [d0, d1, d2, since]);
  // the live reasoning tail (last ~2 lines) - a real Zwischenmeldung instead of a
  // dead wait; the model streams thinking ~9s before the prose.
  const tail = (preview || "").replace(/\s+/g, " ").trim().slice(-180);
  return (
    <View style={{ paddingTop: 10, paddingLeft: 2, gap: 4 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Ionicons name="sparkles" size={13} color={t.accent2} />
        <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>{tr("chat.thinking")}</Text>
        <View style={{ flexDirection: "row", gap: 3, marginLeft: 1 }}>
          {[d0, d1, d2].map((d, i) => (
            <Animated.View key={i} style={isWeb
              ? [{ width: 4, height: 4, borderRadius: 2, backgroundColor: t.accent2 }, webMotion.dot, { animationDelay: `${i * 160}ms` } as object]
              : { width: 4, height: 4, borderRadius: 2, backgroundColor: t.accent2, opacity: d }} />
          ))}
        </View>
        {secs >= 2 ? <Text style={{ color: t.txtTertiary, fontSize: 11 }}>· {secs}s</Text> : null}
      </View>
      {tail ? (
        <Text numberOfLines={2} style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 15, fontStyle: "italic", paddingLeft: 21 }}>
          {tail}
        </Text>
      ) : null}
    </View>
  );
}
