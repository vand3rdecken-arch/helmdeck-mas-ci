"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const expo_modules_core_1 = require("expo-modules-core");
/**
 * `requireOptionalNativeModule`, NOT `requireNativeModule`.
 *
 * The strict form THROWS when the native module is absent, and absent is a
 * legitimate state here rather than a bug: an OTA JS bundle always runs against
 * whatever binary is already on the phone, so a bundle carrying this file can
 * land on an APK built before this module existed. The strict form would turn
 * that into a white screen at import time. This is exactly the reasoning
 * surfaces/app/src/data/voice.ts already applies to expo-audio and expo-speech-
 * recognition - same trap, same answer.
 *
 * Null here means "this build cannot", and every caller degrades instead of
 * crashing.
 */
exports.default = (0, expo_modules_core_1.requireOptionalNativeModule)("GlassesBridge");
