"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SCRIPT = fs.readFileSync(
  path.join(__dirname, "..", "dashboard", "web", "customer-placement-client.js"),
  "utf8"
);

function abortError() {
  const error = new Error("aborted");
  error.name = "AbortError";
  return error;
}

function createStatusNode() {
  const strong = {textContent: ""};
  return {
    dataset: {},
    querySelector(selector) {
      return selector === "strong" ? strong : null;
    },
    strong,
  };
}

function installHarness(nativeFetch, {immediateTimers = false} = {}) {
  const statusNode = createStatusNode();
  const originalFetch = nativeFetch;

  global.window = {
    fetch: nativeFetch,
    location: {href: ""},
    setTimeout(callback, delay) {
      if (immediateTimers && delay >= 8000) {
        queueMicrotask(callback);
        return 1;
      }
      return setTimeout(callback, delay);
    },
    clearTimeout(handle) {
      if (handle !== 1) clearTimeout(handle);
    },
  };
  global.document = {
    getElementById(id) {
      return id === "runtime-placement-status" ? statusNode : null;
    },
  };
  Object.defineProperty(global, "navigator", {
    value: {},
    configurable: true,
    writable: true,
  });
  global.AbortController = AbortController;
  global.URLSearchParams = URLSearchParams;

  vm.runInThisContext(SCRIPT, {filename: "customer-placement-client.js"});

  assert.strictEqual(
    window.fetch,
    originalFetch,
    "explicit placement client must not replace window.fetch"
  );
  assert.equal(typeof window.CapivaraPlacementClient?.loadRuntimes, "function");
  assert.equal(typeof window.CapivaraPlacementClient?.loadRegions, "function");

  return {client: window.CapivaraPlacementClient, statusNode};
}

function cleanupHarness() {
  delete global.window;
  delete global.document;
  delete global.navigator;
}

async function testNoEligibleAgentIsExplicitUnavailable() {
  const {client, statusNode} = installHarness(async input => {
    assert.match(String(input), /^\/api\/customer\/placement\/locations/);
    return new Response(JSON.stringify({
      locations: [{
        region_id: "br-sp",
        name: "São Paulo",
        country_code: "BR",
        availability: "unavailable",
        recommended: false,
      }],
    }), {
      status: 200,
      headers: {"Content-Type": "application/json"},
    });
  });

  await assert.rejects(
    client.loadRegions({game: "dayz", contract: "contract-1"}),
    error => {
      assert.equal(error.code, "placement_no_available_agent");
      assert.equal(error.status, 503);
      return true;
    }
  );
  assert.equal(statusNode.dataset.state, "unavailable");
  assert.match(statusNode.strong.textContent, /Nenhum servidor está disponível/);
  cleanupHarness();
}

async function testAvailableRegionsArePublicAndRecommended() {
  const {client, statusNode} = installHarness(async input => {
    assert.match(String(input), /game=minecraft/);
    assert.match(String(input), /contract=contract-2/);
    return new Response(JSON.stringify({
      locations: [{
        region_id: "br-sp",
        name: "São Paulo",
        country_code: "BR",
        availability: "available",
        recommended: true,
        latency: {value_ms: 18},
      }],
    }), {
      status: 200,
      headers: {"Content-Type": "application/json"},
    });
  });

  const result = await client.loadRegions({game: "minecraft", contract: "contract-2"});
  assert.equal(result.regions.length, 1);
  assert.equal(result.regions[0].id, "br-sp");
  assert.equal(result.regions[0].recommended, true);
  assert.equal(result.regions[0].latency_ms, 18);
  assert.match(result.regions[0].name, /Servidor recomendado/);
  assert.equal(statusNode.dataset.state, "available");
  cleanupHarness();
}

async function testCatalogTimeoutIsControlledWithoutFetchPatch() {
  let calls = 0;
  const {client, statusNode} = installHarness((input, options = {}) => {
    assert.match(String(input), /^\/api\/catalog\/runtimes\?game=dayz/);
    calls += 1;
    return new Promise((resolve, reject) => {
      if (options.signal?.aborted) {
        reject(abortError());
        return;
      }
      options.signal?.addEventListener("abort", () => reject(abortError()), {once: true});
    });
  }, {immediateTimers: true});

  await assert.rejects(
    client.loadRuntimes("dayz"),
    error => {
      assert.equal(error.code, "runtime_catalog_timeout");
      assert.equal(error.status, 504);
      return true;
    }
  );
  assert.equal(calls, 1);
  assert.equal(statusNode.dataset.state, "error");
  assert.match(statusNode.strong.textContent, /demorou demais/);
  cleanupHarness();
}

async function main() {
  await testNoEligibleAgentIsExplicitUnavailable();
  await testAvailableRegionsArePublicAndRecommended();
  await testCatalogTimeoutIsControlledWithoutFetchPatch();
  console.log("customer placement client frontend regressions: OK");
}

main().catch(error => {
  cleanupHarness();
  console.error(error);
  process.exitCode = 1;
});
