"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SCRIPT = fs.readFileSync(
  path.join(__dirname, "..", "dashboard", "web", "customer-placement-selector.js"),
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

function installHarness({nativeFetch, originalOpen, immediateTimers = false}) {
  let domReadyHandler = null;
  const statusNode = createStatusNode();

  global.window = {
    fetch: nativeFetch,
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
    CapivaraRuntimeSelector: {open: originalOpen},
  };
  global.document = {
    getElementById(id) {
      return id === "runtime-placement-status" ? statusNode : null;
    },
    addEventListener(event, handler) {
      if (event === "DOMContentLoaded") domReadyHandler = handler;
    },
  };
  Object.defineProperty(global, "navigator", {
    value: {},
    configurable: true,
    writable: true,
  });
  global.Response = Response;
  global.AbortController = AbortController;
  global.URLSearchParams = URLSearchParams;

  vm.runInThisContext(SCRIPT, {filename: "customer-placement-selector.js"});
  assert.equal(typeof domReadyHandler, "function");
  domReadyHandler();

  return {statusNode, selector: window.CapivaraRuntimeSelector};
}

function cleanupHarness() {
  delete global.window;
  delete global.document;
  delete global.navigator;
}

async function testConcurrentOpenIsDeduplicated() {
  let openCalls = 0;
  let resolveFirst;
  const first = new Promise(resolve => {
    resolveFirst = resolve;
  });

  const {selector} = installHarness({
    nativeFetch: async () => new Response("{}", {status: 200}),
    originalOpen: async () => {
      openCalls += 1;
      if (openCalls === 1) return first;
      return "second-open";
    },
  });

  const contract = {id: "contract-1", game_id: "dayz"};
  const p1 = selector.open(contract);
  const p2 = selector.open(contract);

  assert.strictEqual(p1, p2, "concurrent selector opens must share the same promise");
  assert.equal(openCalls, 0, "the wrapped open starts on the next microtask");
  await Promise.resolve();
  assert.equal(openCalls, 1, "only one original open may run concurrently");

  resolveFirst("first-open");
  assert.equal(await p1, "first-open");
  assert.equal(await p2, "first-open");

  assert.equal(await selector.open(contract), "second-open");
  assert.equal(openCalls, 2, "the in-flight guard must clear after completion");
  cleanupHarness();
}

async function testNoEligibleAgentMapsToUnavailable() {
  const {statusNode} = installHarness({
    nativeFetch: async input => {
      const url = typeof input === "string" ? input : input.url;
      assert.match(url, /^\/api\/customer\/placement\/locations/);
      return new Response(JSON.stringify({
        locations: [
          {
            region_id: "br-sp",
            name: "São Paulo",
            country_code: "BR",
            availability: "unavailable",
            recommended: false,
          },
        ],
      }), {
        status: 200,
        headers: {"Content-Type": "application/json"},
      });
    },
    originalOpen: async () => undefined,
  });

  const response = await window.fetch("/api/customer/regions");
  const body = await response.json();

  assert.equal(response.status, 503);
  assert.equal(body.code, "placement_no_available_agent");
  assert.equal(statusNode.dataset.state, "unavailable");
  assert.match(statusNode.strong.textContent, /Nenhum servidor está disponível/);
  cleanupHarness();
}

async function testCatalogTimeoutReturns504AndOpenGuardClears() {
  let catalogAttempts = 0;
  let openCalls = 0;

  const {selector, statusNode} = installHarness({
    immediateTimers: true,
    nativeFetch: (input, options = {}) => {
      const url = typeof input === "string" ? input : input.url;
      if (!url.startsWith("/api/catalog/runtimes")) {
        return Promise.resolve(new Response("{}", {status: 200}));
      }

      catalogAttempts += 1;
      if (catalogAttempts > 1) {
        return Promise.resolve(new Response(JSON.stringify({runtimes: []}), {
          status: 200,
          headers: {"Content-Type": "application/json"},
        }));
      }

      return new Promise((resolve, reject) => {
        if (options.signal?.aborted) {
          reject(abortError());
          return;
        }
        options.signal?.addEventListener("abort", () => reject(abortError()), {once: true});
      });
    },
    originalOpen: async () => {
      openCalls += 1;
      const response = await window.fetch("/api/catalog/runtimes?game=dayz");
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.error);
      }
      return "ok";
    },
  });

  const contract = {id: "contract-2", game_id: "dayz"};
  await assert.rejects(selector.open(contract), /tempo limite/);
  assert.equal(openCalls, 1);
  assert.equal(catalogAttempts, 1);
  assert.equal(statusNode.dataset.state, "error");

  const directTimeout = await window.fetch("/api/catalog/runtimes?game=dayz&retry=timeout-check");
  assert.equal(directTimeout.status, 200, "second catalog attempt is configured as healthy");

  assert.equal(await selector.open(contract), "ok");
  assert.equal(openCalls, 2, "openingPromise must clear after a rejected open");
  cleanupHarness();
}

async function main() {
  await testConcurrentOpenIsDeduplicated();
  await testNoEligibleAgentMapsToUnavailable();
  await testCatalogTimeoutReturns504AndOpenGuardClears();
  console.log("customer placement selector frontend regressions: OK");
}

main().catch(error => {
  cleanupHarness();
  console.error(error);
  process.exitCode = 1;
});
