// Native stub — the phone scans a QR (camera + App Link), it never generates one.
// The web variant (qrgen.web.ts) does the real generation for the desktop UI.
export async function qrDataUrl(_link: string): Promise<string> {
  return "";
}
