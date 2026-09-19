"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const selectorPath = path.join(root, "dashboard", "web", "runtime-selector.js");
const placementClientPath = path.join(root, "dashboard", "web", "customer-placement-client.js");
const htmlPath = path.join(root, "dashboard", "web", "customer.html");
const selector = fs.readFileSync(selectorPath, "utf8");
const placementClient = fs.readFileSync(placementClientPath, "utf8");
const html = fs.readFileSync(htmlPath, "utf8");

assert.match(
  selector,
  /CapivaraPlacementClient/,
  "runtime selector must depend explicitly on CapivaraPlacementClient"
);
assert.match(
  selector,
  /\.loadRuntimes\(game\)/,
  "runtime catalog hydration must be loaded through the explicit placement client"
);
assert.match(
  selector,
  /\/api\/catalog\/hierarchy\?game=/,
  "runtime discovery must use the canonical catalog hierarchy"
);
assert.match(
  selector,
  /\.loadRegions\(\{/,
  "placement locations must be loaded through the explicit placement client"
);
assert.match(
  selector,
  /let openingPromise = null/,
  "canonical selector must own its in-flight open guard"
);
assert.match(
  selector,
  /if \(openingPromise\) return openingPromise/,
  "concurrent opens must be de-duplicated in the canonical selector"
);
assert.doesNotMatch(
  selector,
  /\/api\/customer\/regions/,
  "canonical selector must not use the legacy generic regions endpoint"
);
assert.doesNotMatch(
  selector,
  /window\.fetch\s*=/,
  "canonical selector must never monkey patch window.fetch"
);
assert.match(
  html,
  /customer-placement-client\.js\?v=3/,
  "customer page must load the explicit placement client"
);
assert.match(
  placementClient,
  /context\.runtime \|\| context\.runtime_id/,
  "placement client must accept the selected runtime"
);
assert.match(
  placementClient,
  /params\.set\("runtime", runtime\)/,
  "placement client must send runtime to the public locations endpoint"
);
assert.match(
  selector,
  /runtime: runtimeId/,
  "runtime selector must request locations for the selected runtime"
);
assert.match(
  selector,
  /placementRequestGeneration/,
  "runtime-aware placement requests must discard stale responses"
);
assert.match(
  selector,
  /placementAbortController/,
  "superseded placement requests must be aborted"
);
assert.match(
  selector,
  /el\.submit\.disabled = !state\.placementReady/,
  "creation must remain disabled until runtime-aware placement succeeds"
);
const placementClientIndex = html.indexOf("/customer-placement-client.js?v=3");
const runtimeSelectorIndex = html.indexOf("/runtime-selector.js?v=7");
assert.ok(
  placementClientIndex >= 0 && runtimeSelectorIndex > placementClientIndex,
  "customer page must load the canonical selector after the placement client"
);
assert.doesNotMatch(
  html,
  /customer-placement-selector\.js/,
  "customer page must not load the removed placement shim"
);

console.log("canonical runtime selector placement contract: OK");
