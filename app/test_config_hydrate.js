// Verification for the desktop login change (A1): a session the user logged
// into must SURVIVE a relaunch.
//
// Background: desktop/main.js used to mint an owner device token at every
// launch and inject it into the SPA's #cfg hash - opening the app was an owner
// login with no credential. That mint is gone. But config.ts's hydrate() used
// to let the hash REPLACE the whole config, and anything it omitted was
// dropped. With no token in the hash any more, replacing would throw away the
// session in localStorage and demand a login at every single launch. That is
// the failure mode that gets a security fix reverted, so it gets a test.
//
// This runs the REAL src/data/config.ts: transpiled with the repo's own
// TypeScript, loaded under node with its native-only imports stubbed. Not a
// reimplementation of the logic - the shipped file.
//
// Run: node app/test_config_hydrate.js     (from the repo root or app/)

const fs = require("fs");
const path = require("path");
const Module = require("module");

const APP = __dirname;
const ts = require(path.join(APP, "node_modules", "typescript"));

const fails = [];
function ok(cond, msg) {
  console.log((cond ? "  ok   - " : "  FAIL - ") + msg);
  if (!cond) fails.push(msg);
}

// --- stubs for everything config.ts imports that node cannot load -----------
function makeZustandCreate() {
  return (fn) => {
    let state;
    const set = (patch) => {
      state = Object.assign({}, state,
        typeof patch === "function" ? patch(state) : patch);
    };
    const get = () => state;
    state = fn(set, get);
    const use = (sel) => (sel ? sel(state) : state);
    use.getState = get;
    use.setState = set;
    return use;
  };
}

const STUBS = {
  "expo-secure-store": { getItemAsync: async () => null, setItemAsync: async () => {} },
  "react-native": { Platform: { OS: "web" } },
  "zustand": { create: makeZustandCreate() },
  "@/i18n/core": { t: (k) => k },
  "./analytics": { track: () => {} },
  "./demo": { useDemo: { getState: () => ({ disable() {} }) } },
  "./e2ee": { generateKeyPair: () => ({ sec: "sec", pub: "pub" }) },
};

const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (Object.prototype.hasOwnProperty.call(STUBS, request)) return "STUB:" + request;
  return origResolve.call(this, request, ...rest);
};
const origLoad = Module._load;
Module._load = function (request, ...rest) {
  if (Object.prototype.hasOwnProperty.call(STUBS, request)) return STUBS[request];
  return origLoad.call(this, request, ...rest);
};

// --- load the real config.ts, optionally with the PRE-FIX hydrate ----------
function loadConfig({ legacyHydrate = false } = {}) {
  const srcPath = path.join(APP, "src", "data", "config.ts");
  let src = fs.readFileSync(srcPath, "utf8");

  if (legacyHydrate) {
    // Restore the exact pre-fix body so the test can prove it catches the bug.
    const fixedStart = src.indexOf("        // Desktop (Electron) hands the daemon URL via the URL hash");
    const fixedEnd = src.indexOf("      } else {", fixedStart);
    if (fixedStart < 0 || fixedEnd < 0) throw new Error("could not locate hydrate's web branch");
    src = src.slice(0, fixedStart) +
      '        const hash = globalThis.location?.hash ?? "";\n' +
      "        const m = /[#&]cfg=([^&]+)/.exec(hash);\n" +
      "        if (m) get().set(JSON.parse(atob(decodeURIComponent(m[1]))));\n" +
      "        else { const raw = globalThis.localStorage?.getItem(KEY); if (raw) set({ ...JSON.parse(raw) }); }\n" +
      src.slice(fixedEnd);
  }

  const js = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: "config.ts",
  }).outputText;

  const out = path.join(require("os").tmpdir(),
    "helmdeck-config-" + (legacyHydrate ? "legacy" : "fixed") + ".js");
  fs.writeFileSync(out, js);
  delete require.cache[out];
  return require(out).useConfig;
}

// --- a fake browser --------------------------------------------------------
const KEY = "helmdeck.config";
function browser({ stored, hash }) {
  const mem = new Map();
  if (stored) mem.set(KEY, JSON.stringify(stored));
  globalThis.localStorage = {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, v),
  };
  globalThis.location = { hash: hash || "" };
  globalThis.atob = (b) => Buffer.from(b, "base64").toString("binary");
  return mem;
}

function cfgHash(obj) {
  return "#cfg=" + encodeURIComponent(Buffer.from(JSON.stringify(obj)).toString("base64"));
}

// The hash desktop/main.js actually builds now - read from the file so this
// test fails if someone puts a token back into it.
function realDesktopHashFields() {
  const main = fs.readFileSync(path.join(APP, "..", "desktop", "main.js"), "utf8");
  const block = /const cfg = Buffer\.from\(JSON\.stringify\(\{([\s\S]*?)\}\)\)/.exec(main);
  if (!block) throw new Error("could not find the cfg block in desktop/main.js");
  return block[1];
}

async function scenario(name, { stored, hash, legacyHydrate }) {
  browser({ stored, hash });
  const useConfig = loadConfig({ legacyHydrate });
  await useConfig.getState().hydrate();
  const s = useConfig.getState();
  console.log("  [%s] token=%j baseUrl=%j", name, s.token, s.baseUrl);
  return s;
}

async function main() {
  console.log("desktop/main.js must not hand the SPA a token");
  const fields = realDesktopHashFields();
  ok(!/\btoken\b/.test(fields), "no `token` key in the #cfg payload");
  ok(/baseUrl/.test(fields), "baseUrl still handed over");

  const DESKTOP_HASH = cfgHash({ baseUrl: "http://localhost:8140",
                                 setup: { port: 8199, nonce: "abc" } });

  console.log("\nfirst launch - nothing stored yet");
  let s = await scenario("fresh", { stored: null, hash: DESKTOP_HASH });
  ok(s.token === "", "no token -> the app will show the login screen");
  ok(s.baseUrl === "http://localhost:8140", "baseUrl came from the hash");

  console.log("\nrelaunch after a real login - THE lockout regression");
  const LOGGED_IN = { baseUrl: "http://localhost:8140", token: "sdk_real_session",
                      relayUrl: "", room: "", daemonPub: "", mySec: "", myPub: "" };
  s = await scenario("relaunch", { stored: LOGGED_IN, hash: DESKTOP_HASH });
  ok(s.token === "sdk_real_session", "the logged-in session SURVIVED the relaunch");
  ok(s.baseUrl === "http://localhost:8140", "baseUrl still applied");

  console.log("\nhash carrying an explicit empty token must not clobber it");
  s = await scenario("emptytoken", {
    stored: LOGGED_IN,
    hash: cfgHash({ baseUrl: "http://localhost:8140", token: "" }),
  });
  ok(s.token === "sdk_real_session", "empty token in the hash ignored");

  console.log("\nhash must still be able to CHANGE baseUrl");
  s = await scenario("newport", {
    stored: Object.assign({}, LOGGED_IN, { baseUrl: "http://localhost:9999" }),
    hash: DESKTOP_HASH,
  });
  ok(s.baseUrl === "http://localhost:8140", "hash overrode the stale stored baseUrl");
  ok(s.token === "sdk_real_session", "...without losing the session");

  console.log("\nlogout must actually log out");
  s = await scenario("loggedout", {
    stored: Object.assign({}, LOGGED_IN, { token: "" }),
    hash: DESKTOP_HASH,
  });
  ok(s.token === "", "a cleared session stays cleared");

  console.log("\nregression proof - the PRE-FIX hydrate on the same input");
  s = await scenario("legacy", { stored: LOGGED_IN, hash: DESKTOP_HASH, legacyHydrate: true });
  ok(s.token === "", "old code DID drop the session (this is the bug being fixed)");

  console.log();
  if (fails.length) {
    console.log("FAILED (" + fails.length + "):");
    fails.forEach((m) => console.log("  - " + m));
    process.exit(1);
  }
  console.log("all green");
}

main().catch((e) => { console.error(e); process.exit(1); });
