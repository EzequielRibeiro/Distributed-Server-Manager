"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SCRIPT = fs.readFileSync(
  path.join(__dirname, "..", "dashboard", "web", "customer-placement-selector.js"),
  "utf8"
);

function installHarness({loadRegions, originalOpen}) {
  let domReadyHandler = null;
  const nativeFetch = async () => new Response("{}", {status: 200});

  global.window = {
    fetch: nativeFetch,
    CapivaraPlacementClient: {loadRegions},
    CapivaraRuntimeSelector: {open: originalOpen},
  };
  global.document = {
    addEventListener(event, handler) {
      if (event === "DOMContentLoaded") domReadyHandler = handler;
    },
  };

  vm.runInThisContext(SCRIPT, {filename: "customer-placement-selector.js"});
  assert.equal(typeof domReadyHandler, "function");
  assert.strictEqual(window.fetch, nativeFetch, "adapter must not replace window.fetch");
  domReadyHandler();

  return {selector: window.CapivaraRuntimeSelector};
}

function cleanupHarness() {
  delete global.window;
  delete global.document;
}

async function testConcurrentOpenIsDeduplicatedAndPreflightsPlacement() {
  let placementCalls = 0;
  let openCalls = 0;
  let resolveFirst;
  const first = new Promise(resolve => {
    resolveFirst = resolve;
  });

  const {selector} = installHarness({
    loadRegions: async context => {
      placementCalls += 1;
      assert.deepEqual(context, {contract: "contract-1", game: "dayz"});
      return {regions: [{id: "br-sp"}]};
    },
    originalOpen: async () => {
      openCalls += 1;
      if (openCalls === 1) return first;
      return "second-open";
    },
  });

  const contract = {id: "contract-1", game_id: "dayz"};
  const p1 = selector.open(contract);
  const p2 = selector.open(contract);

  assert.strictEqual(p1, p2, "concurrent opens must share the same promise");
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(placementCalls, 1, "placement preflight must run once per in-flight open");
  assert.equal(openCalls, 1, "only one selector open may run concurrently");

  resolveFirst("first-open");
  assert.equal(await p1, "first-open");
  assert.equal(await p2, "first-open");

  assert.equal(await selector.open(contract), "second-open");
  assert.equal(placementCalls, 2, "guard must clear after completion");
  assert.equal(openCalls, 2);
  cleanupHarness();
}

async function testUnavailablePlacementStopsSelectorOpenAndGuardClears() {
  let placementCalls = 0;
  let openCalls = 0;

  const unavailable = new Error("Nenhum servidor elegível foi localizado para este jogo no momento.");
  unavailable.code = "placement_no_available_agent";

  const {selector} = installHarness({
    loadRegions: async () => {
      placementCalls += 1;
      if (placementCalls === 1) throw unavailable;
      return {regions: [{id: "br-sp"}]};
    },
    originalOpen: async () => {
      openCalls += 1;
      return "ok";
    },
  });

  const contract = {id: "contract-2", game_id: "dayz"};
  await assert.rejects(selector.open(contract), /Nenhum servidor elegível/);
  assert.equal(openCalls, 0, "selector must not open when placement preflight is unavailable");

  assert.equal(await selector.open(contract), "ok");
  assert.equal(placementCalls, 2, "rejected preflight must release in-flight guard");
  assert.equal(openCalls, 1);
  cleanupHarness();
}

async function main() {
  await testConcurrentOpenIsDeduplicatedAndPreflightsPlacement();
  await testUnavailablePlacementStopsSelectorOpenAndGuardClears();
  console.log("customer placement selector adapter regressions: OK");
}

main().catch(error => {
  cleanupHarness();
  console.error(error);
  process.exitCode = 1;
});
