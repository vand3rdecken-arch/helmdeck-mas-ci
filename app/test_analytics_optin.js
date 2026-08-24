// Verification for A3: analytics must be OPT-IN, matching the corrected
// privacy policy (relay/relay.py) which now says nothing is sent to PostHog
// unless the user turns it on in More -> Datenschutz.
//
// Runs the REAL src/data/analytics.ts (transpiled with the repo's own
// TypeScript, PostHog/AsyncStorage/zustand stubbed) - not a reimplementation.
//
// Run: node app/test_analytics_optin.js     (from the repo root or app/)

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

// --- a fake PostHog that records what it was told, never talks to a network -
let posthogCalls = [];
let lastConstructOptions = null;
class FakePostHog {
  constructor(key, opts) {
    posthogCalls.push(["construct", key, opts]);
    lastConstructOptions = opts;
    this._optedIn = !!opts.defaultOptIn;
  }
  optIn() { posthogCalls.push(["optIn"]); this._optedIn = true; }
  optOut() { posthogCalls.push(["optOut"]); this._optedIn = false; }
  capture(event, props) { posthogCalls.push(["capture", event, props]); }
}

function makeZustandCreate() {
  return (fn) => {
    let state;
    const set = (patch) => {
      state = Object.assign({}, state, typeof patch === "function" ? patch(state) : patch);
    };
    const get = () => state;
    state = fn(set, get);
    const use = (sel) => (sel ? sel(state) : state);
    use.getState = get;
    return use;
  };
}

const storage = new Map();
const STUBS = {
  "posthog-react-native": { __esModule: true, default: FakePostHog },
  "@react-native-async-storage/async-storage": {
    __esModule: true,
    default: {
      getItem: async (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: async (k, v) => { storage.set(k, v); },
    },
  },
  zustand: { create: makeZustandCreate() },
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

function loadAnalytics() {
  const srcPath = path.join(APP, "src", "data", "analytics.ts");
  const src = fs.readFileSync(srcPath, "utf8");
  const js = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: "analytics.ts",
  }).outputText;
  const out = path.join(require("os").tmpdir(), "helmdeck-analytics-test.js");
  fs.writeFileSync(out, js);
  delete require.cache[out];
  return require(out);
}

async function main() {
  console.log("fresh module load - before hydrate() ever runs");
  const { useAnalytics, track } = loadAnalytics();
  ok(useAnalytics.getState().enabled === false,
     "enabled defaults to false - opt-IN, not opt-out");

  track("should_not_fire");
  ok(posthogCalls.length === 0,
     "track() before hydrate/opt-in touches PostHog NOT AT ALL (no construct call)");

  console.log("\nhydrate() with nothing stored (fresh install)");
  await useAnalytics.getState().hydrate();
  ok(useAnalytics.getState().enabled === false, "stays disabled with no stored preference");
  ok(posthogCalls.length === 0,
     "the PostHog client was never constructed for a disabled user");

  track("still_should_not_fire");
  ok(posthogCalls.length === 0, "and still nothing after another track() call");

  console.log("\nuser turns it ON in More -> Datenschutz");
  useAnalytics.getState().setEnabled(true);
  const constructCall = posthogCalls.find((c) => c[0] === "construct");
  ok(!!constructCall, "constructing the client now, on first real use");
  ok(constructCall[2].defaultOptIn === false,
     "...but the SDK's OWN default is still opted-out (defense in depth)");
  ok(posthogCalls.some((c) => c[0] === "optIn"), "and optIn() was called explicitly");

  posthogCalls = [];
  track("card_move", { lane: "review" });
  ok(posthogCalls.some((c) => c[0] === "capture" && c[1] === "card_move"),
     "NOW a real event actually reaches PostHog");

  console.log("\nuser turns it back OFF");
  useAnalytics.getState().setEnabled(false);
  posthogCalls = [];
  track("should_not_fire_again");
  ok(posthogCalls.length === 0, "track() is silent again immediately");

  console.log("\nrelaunch: hydrate() restores a previously-given opt-IN");
  // Simulate a PRIOR session that opted in - the module above just opted back
  // out, so re-arm storage directly rather than relying on call order.
  useAnalytics.getState().setEnabled(true);
  posthogCalls = [];
  const fresh = loadAnalytics();
  ok(fresh.useAnalytics.getState().enabled === false,
     "still false before hydrate runs, even though '1' is in storage");
  await fresh.useAnalytics.getState().hydrate();
  ok(fresh.useAnalytics.getState().enabled === true,
     "hydrate() restores the stored opt-in");
  ok(posthogCalls.some((c) => c[0] === "optIn"),
     "and calls optIn() - not optOut() - to match it");

  console.log();
  if (fails.length) {
    console.log("FAILED (" + fails.length + "):");
    fails.forEach((m) => console.log("  - " + m));
    process.exit(1);
  }
  console.log("all green");
}

main().catch((e) => { console.error(e); process.exit(1); });
