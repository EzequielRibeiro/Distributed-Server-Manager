"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const selectorPath = path.join(root, "dashboard", "web", "runtime-selector.js");
const htmlPath = path.join(root, "dashboard", "web", "customer.html");
const selector = fs.readFileSync(selectorPath, "utf8");
const html = fs.readFileSync(htmlPath, "utf8");

assert.match(
  selector,
  /CapivaraPlacementClient/,
  "runtime selector must depend explicitly on CapivaraPlacementClient"
);
assert.match(
  selector,
  /\.loadRuntimes\(game\)/,
  "runtime catalog must be loaded through the explicit placement client"
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
  /customer-placement-client\.js\?v=1/,
  "customer page must load the explicit placement client"
);
assert.match(
  html,
  /runtime-selector\.js\?v=3/,
  "customer page must load the canonical selector after the placement client"
);
assert.doesNotMatch(
  html,
  /customer-placement-selector\.js/,
  "customer page must not load the removed placement shim"
);

console.log("canonical runtime selector placement contract: OK");
