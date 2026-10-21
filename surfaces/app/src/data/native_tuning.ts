// Applies the workspace's `native_tuning` (spine/ops/native_tuning.py) to the
// native modules. The native code keeps its old constants as defaults; this only
// overrides them, so an old daemon (no key), an old APK (no hook) or a bad value
// changes nothing. Tuning the voice feel is therefore an OTA/daemon change, not a
// store submission (ops/docs/backlog/native-release-diet).
import LiveMic from "../../modules/livemic";

type Tuning = Record<string, unknown>;

const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** The vad_* / dictation_* keys, renamed to what LiveMicModule.configure reads. */
export function liveMicConfig(t: Tuning): Record<string, number> {
  const map: Record<string, string> = {
    vad_preroll_frames: "preroll_frames", vad_min_speech_frames: "min_speech_frames",
    vad_end_silence_frames: "end_silence_frames", vad_max_utterance_frames: "max_utterance_frames",
    vad_abs_floor: "abs_floor", vad_snr: "snr", dictation_chunk_samples: "chunk_samples",
  };
  const out: Record<string, number> = {};
  for (const [from, to] of Object.entries(map)) if (num(t[from])) out[to] = t[from] as number;
  return out;
}

/** The glass_* keys, whole - the services pick theirs out by name. */
export function glassTuning(t: Tuning): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(t)) if (k.startsWith("glass_") && num(v)) out[k] = v;
  return out;
}

export async function applyNativeTuning(t: unknown): Promise<void> {
  if (!t || typeof t !== "object") return;
  const tuning = t as Tuning;
  try {
    const cfg = liveMicConfig(tuning);
    if (LiveMic && typeof LiveMic.configure === "function" && Object.keys(cfg).length) {
      LiveMic.configure(cfg);
    }
    const g = glassTuning(tuning);
    if (Object.keys(g).length) (await import("./glasses")).tune(JSON.stringify(g));
  } catch {
    // a convenience at launch: never let it reach the launch path
  }
}
