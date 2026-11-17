"use strict";

// Verifies the actual mobile select options, not only source-code markers.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(
  path.join(__dirname, "../dashboard/web/runtime-selector.js"), "utf8"
);
const marker = '    document.addEventListener("DOMContentLoaded", installEvents);';
assert.ok(script.includes(marker), "expected selector startup marker");
const instrumented = script.replace(
  marker,
  '    window.__testAgentChoices = {state, renderRegions, installEvents, serverLocationLabel};\n' + marker
);

function element() {
  return {hidden: false, disabled: false, checked: false, textContent: "",
    listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
  };
}

const elements = new Map();
const ids = ["runtime-region", "runtime-region-help", "runtime-region-step",
  "runtime-summary-step", "minecraft-runtime-notice", "votifier-creation-option",
  "votifier-creation-enabled", "minecraft-eula-accepted", "create-instance-submit",
  "runtime-region-fallback"];
for (const id of ids) elements.set(id, element());
const select = elements.get("runtime-region");
select.options = [];
select.value = "";
select.replaceChildren = (...items) => {
  select.options = [...items];
  select.value = items[0]?.value || "";
};
select.append = item => select.options.push(item);
const context = {
  window: {},
  document: {
    getElementById(id) { return elements.get(id) || null; },
    addEventListener() {},
  },
  Option: class { constructor(text, value) { this.text = text; this.value = value; } },
  Intl, URLSearchParams, console, AbortController,
};
vm.runInNewContext(instrumented, context, {filename: "runtime-selector.js"});
const selector = context.window.__testAgentChoices;
const brRef1 = "srv-" + "a".repeat(24);
const brRef2 = "srv-" + "b".repeat(24);
const usRef = "srv-" + "c".repeat(24);
selector.state.regions = [
  {
    id: "br-sp", country_code: "BR", country_name: "Brasil", state_name: "São Paulo",
    latency_ms: 10, recommended: true,
    servers: [
      {ref: brRef1, label: "Agent Horizon", country_code: "BR",
        state_name: "São Paulo", latency_ms: 10, recommended: true},
      {ref: brRef2, label: "Agent Secundário", country_code: "BR",
        state_name: "São Paulo", latency_ms: 22, recommended: false},
    ],
  },
  {
    id: "us-ma", country_code: "US", country_name: "Estados Unidos", state_name: "Massachusetts",
    latency_ms: 103, recommended: false,
    servers: [
      {ref: usRef, label: "Vps", country_code: "US",
        state_name: "Massachusetts", latency_ms: 103, recommended: true},
    ],
  },
];
selector.state.placementReady = true;
selector.renderRegions();
const choices = select.options;
assert.equal(choices.length, 4, "three eligible Agents must have three separate select options");
assert.equal(choices[0].value, "");
assert.equal(new Set(choices.slice(1).map(x => x.value)).size, 3);
assert.match(choices[1].text, /🇧🇷 Brasil.*São Paulo.*Ping estimado ~10 ms.*\(recomendado\)/);
assert.match(choices[2].text, /🇧🇷 Brasil.*São Paulo.*Ping estimado ~22 ms/);
assert.match(choices[3].text, /🇺🇸 Estados Unidos.*Massachusetts.*Ping estimado ~103 ms/);
assert.equal(choices.filter(item => item.text.includes("(recomendado)")).length, 1);
assert.ok(choices.slice(1).every(item => !/(Agent Horizon|Agent Secundário|Vps)/.test(item.text)),
  "Agent administrative names must never appear in customer location labels");
assert.doesNotMatch(choices[3].text, /recomendado/);
selector.installEvents();
select.value = usRef;
select.listeners.change();
assert.equal(selector.state.region.id, "us-ma");
assert.equal(selector.state.serverRef, usRef);
assert.equal(selector.state.allowCrossRegion, false);
console.log("individual Agent locations in mobile select: OK");
