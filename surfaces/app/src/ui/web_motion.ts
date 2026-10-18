import { StyleSheet } from "react-native";

// Looping motion for WEB as real CSS animations (compositor thread). Core Animated has no native driver on
// web, so every `Animated.loop` re-rendered its style 60x/s from JavaScript - with a few running tiles the
// desktop window sat at ~80% CPU (measured 2026-10-18). Native keeps its Animated loops (native driver).
// react-native-web compiles animationKeyframes into a @keyframes rule ONLY through StyleSheet.create;
// inline it is dropped silently (measured: animation-name "none").
const loop = (keyframes: object, ms: number, timing = "ease-in-out") =>
  ({ animationKeyframes: [keyframes], animationDuration: `${ms}ms`, animationIterationCount: "infinite",
     animationTimingFunction: timing }) as object;

const fade = (lo: number) => ({ "0%": { opacity: 1 }, "50%": { opacity: lo }, "100%": { opacity: 1 } });

export const webMotion = StyleSheet.create({
  /** chat_threads StatusRing: one turn per 900 ms */
  spin900: loop({ "0%": { transform: [{ rotate: "0deg" }] }, "100%": { transform: [{ rotate: "360deg" }] } }, 900, "linear"),
  /** compaction marker glyph: one turn per 1.6 s */
  spin1600: loop({ "0%": { transform: [{ rotate: "0deg" }] }, "100%": { transform: [{ rotate: "360deg" }] } }, 1600, "linear"),
  /** board RunningPulse: 1 -> 0.28 -> 1 over 1.5 s */
  pulse: loop(fade(0.28), 1500),
  /** processes: the step the chain waits on, 1 -> 0.45 -> 1 over 1.6 s */
  wait: loop(fade(0.45), 1600),
  /** compaction marker: 1 -> 0.35 -> 1 over 1.8 s */
  breath: loop(fade(0.35), 1800),
  /** repo_pipeline GateDot ring: grows and fades out, 1.6 s */
  ping: loop({ "0%": { transform: [{ scale: 0.7 }], opacity: 0.5 }, "100%": { transform: [{ scale: 1.9 }], opacity: 0 } }, 1600, "ease-out"),
  /** thinking indicator dot: 0.25 -> 1 -> 0.25 inside a 960 ms cycle (stagger with animationDelay) */
  dot: loop({ "0%": { opacity: 0.25 }, "31%": { opacity: 1 }, "62%": { opacity: 0.25 }, "100%": { opacity: 0.25 } }, 960, "linear"),
});
