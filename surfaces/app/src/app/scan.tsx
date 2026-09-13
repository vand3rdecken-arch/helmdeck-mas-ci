import { useRouter } from "expo-router";

import { QrScanner } from "@/ui/qr_scanner";

// QR pairing scanner: point the camera at the desktop's "Telefon koppeln" QR.
// The QR holds either a pair link (…/pair?c=CODE, https or helmdeck://) or the
// raw base64 code; QrScanner pulls CODE out and we hand it to /pair, which runs
// the same verified round-trip (api.me) as a tapped deep link.
export default function Scan() {
  const router = useRouter();
  return (
    <QrScanner onCode={(code) => router.replace(`/pair?c=${encodeURIComponent(code)}`)}
      onCancel={() => router.back()} />
  );
}
