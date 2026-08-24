import QRCode from "qrcode";

// Desktop (web/Electron) QR generation for phone pairing. ECC "M" survives glare
// and angle better than "L" at scan time.
export async function qrDataUrl(link: string): Promise<string> {
  try {
    return await QRCode.toDataURL(link, { errorCorrectionLevel: "M", margin: 3, width: 320 });
  } catch {
    return "";
  }
}
