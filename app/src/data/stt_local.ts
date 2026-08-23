import LiveMic from "../../modules/livemic";

/** On-device STT (sherpa-onnx whisper-tiny int8) — the "Gerät" half of the
 *  owner's A/B against the PC's faster-whisper (data/client.ts transcribe).
 *
 *  The model (~104 MB, three files) is NOT in the APK: it downloads over the
 *  phone's own internet straight from Hugging Face on first enable, into
 *  filesDir/stt-whisper-tiny/. The native module does the fetching
 *  (HttpURLConnection) so no expo-file-system dependency is added; files
 *  already present are skipped, so this is cheap after the first run.
 *
 *  tiny, not base, deliberately: on a phone CPU whisper-base is multiple
 *  seconds per utterance - the entire point of on-device is beating the
 *  PC round trip, and only tiny has a chance at that. Quality vs the PC's
 *  base/1.4s is exactly what the A/B is meant to measure. */

const REPO = "https://huggingface.co/csukuangfj/sherpa-onnx-whisper-tiny/resolve/main";
const FILES = ["tiny-encoder.int8.onnx", "tiny-decoder.int8.onnx", "tiny-tokens.txt"];
const DIR = "stt-whisper-tiny";

let ready = false;

export function localSttSupported(): boolean {
  return LiveMic != null && typeof LiveMic.initLocalStt === "function";
}

/** Download (first time) + init. Throws with a human-readable reason. */
export async function ensureLocalStt(lang: string): Promise<void> {
  if (ready) return;
  const mic = LiveMic;
  if (!mic || typeof mic.initLocalStt !== "function") {
    throw new Error("Dieses APK hat kein Geräte-STT (Update nötig).");
  }
  const dir = await mic.downloadFiles(FILES.map((f) => `${REPO}/${f}`), DIR);
  const ok = mic.initLocalStt(
    `${dir}/tiny-encoder.int8.onnx`,
    `${dir}/tiny-decoder.int8.onnx`,
    `${dir}/tiny-tokens.txt`,
    lang,
  );
  if (!ok) throw new Error("Geräte-STT-Init fehlgeschlagen (sherpa-onnx fehlt im Build?)");
  ready = true;
}

export async function transcribeLocal(b64: string): Promise<string> {
  const mic = LiveMic;
  if (!mic || !ready) throw new Error("Geräte-STT nicht initialisiert");
  return mic.transcribeLocal(b64);
}
