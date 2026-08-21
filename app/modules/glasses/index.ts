import { requireOptionalNativeModule } from "expo-modules-core";

/** The native surface — see android/.../GlassesBridgeModule.kt. */
export interface GlassesBridge {
  /** Persist where the services reach the daemon. Call at pairing time. */
  configure(baseUrl: string, token: string): boolean;
  /** Can this handset run the DAT camera at all (API >= 29)? */
  cameraSupported(): boolean;
  /** `useGlassMic=false` keeps A2DP so the reply is not 8 kHz. */
  listen(useGlassMic: boolean): boolean;
  stopListening(): boolean;
  /** One frame, attached to `cardId`. Refuses a blank id. */
  capture(cardId: string): boolean;
  stopCamera(): boolean;
}

/**
 * `requireOptionalNativeModule`, NOT `requireNativeModule`.
 *
 * The strict form THROWS when the native module is absent, and absent is a
 * legitimate state here rather than a bug: an OTA JS bundle always runs against
 * whatever binary is already on the phone, so a bundle carrying this file can
 * land on an APK built before this module existed. The strict form would turn
 * that into a white screen at import time. This is exactly the reasoning
 * app/src/data/voice.ts already applies to expo-audio and expo-speech-
 * recognition - same trap, same answer.
 *
 * Null here means "this build cannot", and every caller degrades instead of
 * crashing.
 */
export default requireOptionalNativeModule<GlassesBridge>("GlassesBridge");
