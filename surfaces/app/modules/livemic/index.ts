import { requireOptionalNativeModule } from "expo-modules-core";

/** The native surface — see android/.../LiveMicModule.kt.
 *
 *  Raw mic -> VAD -> utterance segments (one WAV blob per finished utterance),
 *  the phone half of the speech-to-speech cascade. `requireOptionalNativeModule`
 *  for the same measured reason as modules/glasses: an OTA bundle can land on
 *  an APK built before this module existed, and null-means-cannot beats a
 *  white screen (see modules/surfaces/glasses/index.ts). */
export interface LiveMicModule {
  /** Open the mic. `voiceComm=true` = AudioSource.VOICE_COMMUNICATION (HW echo
   *  cancel where the handset has one). Idempotent; false = mic unavailable. */
  start(voiceComm: boolean): boolean;
  stop(): boolean;
  /** should_listen gate: mute capture while Henry speaks, so the phone never
   *  transcribes its own speaker. */
  setMuted(m: boolean): boolean;
  /** Fetch model files into filesDir/<dir>/ (skips existing); resolves with
   *  the absolute directory path. Native HttpURLConnection - no expo-file-
   *  system dependency. */
  downloadFiles(urls: string[], dir: string): Promise<string>;
  /** Build the on-device sherpa-onnx recognizer from files on disk. False =
   *  this build has no sherpa AAR (old APK / iOS) or the files are bad. */
  initLocalStt(encoder: string, decoder: string, tokens: string, lang: string): boolean;
  /** Streaming-transducer variant (zipformer/kroko) - the benchmark winner
   *  for German on-device (ops/tools/stt_bench.py 2026-08-23). */
  initLocalTransducer(encoder: string, decoder: string, joiner: string, tokens: string): boolean;
  /** One VAD segment (this module's own WAV shape) -> text, on-device. */
  transcribeLocal(b64: string): Promise<string>;
  addListener(event: "onSegment" | "onState", cb: (e: any) => void): { remove(): void };
}

export interface MicSegment { b64: string; ms: number }
export interface MicState { state: "listening" | "speech" }

export default requireOptionalNativeModule<LiveMicModule>("LiveMic");
