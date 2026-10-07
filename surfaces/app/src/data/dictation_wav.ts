// Pure helpers of the legacy microphone path (no React Native imports, so the
// node selftest can run them): the older LiveMic `start` emits one VAD-cut WAV
// per phrase; dictation wants 0.5 s PCM16 chunks.
export const CHUNK_SAMPLES = 8000;          // 0.5 s @ 16 kHz


const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

export function b64ToBytes(b64: string): Uint8Array {
  const clean = b64.replace(/[^A-Za-z0-9+/]/g, "");
  const out = new Uint8Array(Math.floor(clean.length * 3 / 4));
  let o = 0;
  for (let i = 0; i < clean.length; i += 4) {
    const a = B64.indexOf(clean[i]), b = B64.indexOf(clean[i + 1]);
    const c = i + 2 < clean.length ? B64.indexOf(clean[i + 2]) : -1;
    const d = i + 3 < clean.length ? B64.indexOf(clean[i + 3]) : -1;
    out[o++] = (a << 2) | (b >> 4);
    if (c >= 0) out[o++] = ((b & 15) << 4) | (c >> 2);
    if (d >= 0) out[o++] = ((c & 3) << 6) | d;
  }
  return out.subarray(0, o);
}

export function bytesToB64(u8: Uint8Array): string {
  let s = "";
  for (let i = 0; i < u8.length; i += 3) {
    const a = u8[i], b = i + 1 < u8.length ? u8[i + 1] : 0, c = i + 2 < u8.length ? u8[i + 2] : 0;
    s += B64[a >> 2] + B64[((a & 3) << 4) | (b >> 4)]
      + (i + 1 < u8.length ? B64[((b & 15) << 2) | (c >> 6)] : "=")
      + (i + 2 < u8.length ? B64[c & 63] : "=");
  }
  return s;
}

/** One VAD segment (a 44-byte-header PCM16 mono 16 kHz WAV) -> the same 0.5 s
 *  PCM chunks the streaming mic produces. */
export function feedWav(b64: string, onChunk: (b64: string) => void): void {
  const wav = b64ToBytes(b64);
  const pcm = wav.subarray(44);
  const step = CHUNK_SAMPLES * 2;
  for (let i = 0; i < pcm.length; i += step) onChunk(bytesToB64(pcm.subarray(i, Math.min(i + step, pcm.length))));
}

