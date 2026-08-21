// Ask THIS Electron's Chromium whether full-duplex voice is actually available.
//
// Barge-in on the desktop rests on two recent Chromium additions, and a release
// note is not a runtime: `echoCancellationMode` (Chrome 141+) is the only
// documented way to cancel the page's OWN audio out of a capture stream, and
// `SpeechRecognition.start(MediaStreamTrack)` (Chrome 135+) is the only way to
// hand that stream to the recogniser - which otherwise opens a RAW capture with
// no echo reference at all (chromium speech_recognizer_impl.cc).
//
// data/voice.ts probes the first of those through getSupportedConstraints() at
// runtime, so it degrades correctly on an older shell. This exists to answer the
// separate question the app cannot: whether the Electron version we SHIP has
// them, so the desktop bump can be justified by measurement instead of a table.
//
// Usage:  cd desktop && ELECTRON=$(node -p "require('electron')") && "$ELECTRON" ../tools/probe_duplex.js
// TRAP, paid for here: `about:blank` is an OPAQUE origin, so it is not a secure
// context and `navigator.mediaDevices` is not exposed on it at all. The first
// version of this probe loaded about:blank and cheerfully reported
// "getUserMedia: false, echoCancellation: false" on a Chromium 150 that has
// both - i.e. it would have talked us out of a capability we already had.
// `file://` IS potentially trustworthy, so the page is loaded from disk.
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");

app.whenReady().then(async () => {
  const page = path.join(os.tmpdir(), "hd_duplex_probe.html");
  fs.writeFileSync(page, "<!doctype html><meta charset=utf-8><title>probe</title>");
  const w = new BrowserWindow({ show: false, webPreferences: { offscreen: true } });
  await w.loadFile(page);
  // Auto-grant the microphone: this is a measurement run, and a permission
  // prompt on an offscreen window would just hang.
  w.webContents.session.setPermissionRequestHandler((_wc, _p, cb) => cb(true));
  const out = await w.webContents.executeJavaScript(`(async () => {
    const sc = navigator.mediaDevices && navigator.mediaDevices.getSupportedConstraints
      ? navigator.mediaDevices.getSupportedConstraints() : {};
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    // getSupportedConstraints() is a HINT, not the answer: Chromium does not
    // advertise every constraint it honours there. The only reliable test is to
    // ASK FOR IT and read back what was actually applied.
    let applied = null, gumError = null;
    try {
      const st = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, echoCancellationMode: 'all' } });
      const tr = st.getAudioTracks()[0];
      applied = tr ? tr.getSettings() : null;
      st.getTracks().forEach(t => t.stop());
    } catch (e) { gumError = e.name + ': ' + e.message; }
    return {
      applied, gumError,
      chromium: navigator.userAgent.match(/Chrome\\/([0-9.]+)/)[1],
      echoCancellation: !!sc.echoCancellation,
      echoCancellationMode: !!sc.echoCancellationMode,
      speechRecognition: typeof SR === 'function',
      // start(track) has arity 0 in the IDL either way, so the only honest
      // check is whether the argument is ACCEPTED - done by voice.ts at use
      // time via try/catch. What is observable here is that the constraint
      // exists, which is the half that gates everything.
      startArity: SR ? SR.prototype.start.length : null,
      getUserMedia: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
    };
  })()`);
  console.log(JSON.stringify(out, null, 1));
  const ok = out.echoCancellationMode && out.speechRecognition && out.getUserMedia;
  console.log(ok ? "DUPLEX AVAILABLE" : "DUPLEX NOT AVAILABLE in this shell");
  app.exit(ok ? 0 : 1);
});
