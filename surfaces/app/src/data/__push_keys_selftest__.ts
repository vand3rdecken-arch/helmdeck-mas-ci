// Pushes from several paired PCs (data/push_keys.ts), with REAL NaCl boxes in
// the exact frame format of data/e2ee.ts / spine/comms/e2ee.py
// (base64(nonce || box)). Each "daemon" seals with its own key to this phone.
//
// Run: npx tsc -p tsconfig.invalidate.json && node .invalidate-out/data/__push_keys_selftest__.js
import nacl from "tweetnacl";
import util from "tweetnacl-util";

import { openFromPairings } from "./push_keys";

let fails = 0;
const check = (ok: boolean, msg: string) => {
  console.log((ok ? "  ok  " : "  FAIL ") + msg);
  if (!ok) fails++;
};

const kp = () => { const k = nacl.box.keyPair(); return { pub: util.encodeBase64(k.publicKey), sec: util.encodeBase64(k.secretKey) }; };
const seal = (text: string, sec: string, pub: string) => {
  const nonce = nacl.randomBytes(nacl.box.nonceLength);
  const ct = nacl.box(util.decodeUTF8(text), nonce, util.decodeBase64(pub), util.decodeBase64(sec));
  const f = new Uint8Array(nonce.length + ct.length); f.set(nonce); f.set(ct, nonce.length);
  return util.encodeBase64(f);
};
const open = (frameB64: string, sec: string, pub: string) => {
  const f = util.decodeBase64(frameB64);
  const m = nacl.box.open(f.slice(nacl.box.nonceLength), f.slice(0, nacl.box.nonceLength), util.decodeBase64(pub), util.decodeBase64(sec));
  if (!m) throw new Error("decrypt failed");
  return util.encodeUTF8(m);
};

const phone = kp(), office = kp(), laptop = kp(), stranger = kp();
const saved = { dOffice: { daemonPub: office.pub }, dLaptop: { daemonPub: laptop.pub } };
type P = { title: string; track?: string };

const fromOffice = seal(JSON.stringify({ title: "Buero", track: "c1" }), office.sec, phone.pub);
const fromLaptop = seal(JSON.stringify({ title: "Laptop", track: "c9" }), laptop.sec, phone.pub);
const fromStranger = seal(JSON.stringify({ title: "x" }), stranger.sec, phone.pub);

const a = openFromPairings<P>(fromOffice, phone.sec, office.pub, "dOffice", saved, open);
check(!!a && a.title === "Buero" && a.daemon === undefined, "the active PC's push opens, no switch needed");
const b = openFromPairings<P>(fromLaptop, phone.sec, office.pub, "dOffice", saved, open);
check(!!b && b.title === "Laptop" && b.daemon === "dLaptop", "another paired PC's push opens and names that PC");
check(openFromPairings<P>(fromStranger, phone.sec, office.pub, "dOffice", saved, open) === null,
  "a push no pairing sealed opens nothing");
const tampered = fromLaptop.slice(0, -6) + (fromLaptop.endsWith("AAAA==") ? "BBBB==" : "AAAA==");
check(openFromPairings<P>(tampered, phone.sec, office.pub, "dOffice", saved, open) === null, "a tampered push opens nothing");
check(openFromPairings<P>(fromLaptop, "", office.pub, "dOffice", saved, open) === null, "no keypair, nothing to open");

console.log(fails ? `\nFAIL (${fails})` : "\nPASS - pushes from every paired PC");
process.exit(fails ? 1 : 0);
