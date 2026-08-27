// Tiny bootstrap for `node -r ./_capstest_alias_register.js .capstest-out/...`
// (tsconfig.capstest.json's `paths` mapping is TYPE-CHECK-ONLY - tsc does not
// rewrite emitted `require("@/kernel")` calls, so plain node can't resolve
// them without this). Rewrites the "@/*" alias to the compiled output dir,
// same mapping paths.@/* -> ./src/* uses at the TS level.
const path = require("path");
const Module = require("module");
const outDir = path.join(__dirname, ".capstest-out");
const orig = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (request.startsWith("@/")) {
    return orig.call(this, path.join(outDir, request.slice(2)), ...rest);
  }
  return orig.call(this, request, ...rest);
};
