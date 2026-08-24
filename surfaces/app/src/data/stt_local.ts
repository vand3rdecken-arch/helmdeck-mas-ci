import LiveMic from "../../modules/livemic";

/** On-device STT — the "Gerät" half of the owner's A/B against the PC ear
 *  (data/client.ts transcribe -> daemon parakeet).
 *
 *  Benchmarked 2026-08-23 (ops/tools/stt_bench.py, 36 German utterances, clean +
 *  8 kHz telephone band): the German kroko streaming zipformer is the device
 *  winner - WER 11.4%/12.9% at 0.33s median on the PC, vs whisper-tiny's
 *  29.9%/44.7% at 0.65s. Smaller too (~71 MB vs ~104 MB), and its 8 kHz
 *  robustness keeps the glasses-mic door open.
 *
 *  The model is NOT in the APK: it downloads over the phone's own internet
 *  straight from Hugging Face on first enable, into filesDir/stt-kroko-de/.
 *  The native module does the fetching (HttpURLConnection) so no
 *  expo-file-system dependency; files already present are skipped. */

const REPO = "https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-de-kroko-2025-08-06/resolve/main";
const FILES = ["encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"];
const DIR = "stt-kroko-de";

let ready = false;

export function localSttSupported(): boolean {
  return LiveMic != null && typeof LiveMic.initLocalTransducer === "function";
}

/** Download (first time) + init. Throws with a human-readable reason. */
export async function ensureLocalStt(_lang: string): Promise<void> {
  if (ready) return;
  const mic = LiveMic;
  if (!mic || typeof mic.initLocalTransducer !== "function") {
    throw new Error("Dieses APK hat kein Geräte-STT (Update nötig).");
  }
  const dir = await mic.downloadFiles(FILES.map((f) => `${REPO}/${f}`), DIR);
  const ok = mic.initLocalTransducer(
    `${dir}/encoder.onnx`, `${dir}/decoder.onnx`, `${dir}/joiner.onnx`, `${dir}/tokens.txt`,
  );
  if (!ok) throw new Error("Geräte-STT-Init fehlgeschlagen (sherpa-onnx fehlt im Build?)");
  ready = true;
}

export async function transcribeLocal(b64: string): Promise<string> {
  const mic = LiveMic;
  if (!mic || !ready) throw new Error("Geräte-STT nicht initialisiert");
  return mic.transcribeLocal(b64);
}
