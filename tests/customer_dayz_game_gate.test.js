// Regression: non-DayZ customer instances never expose the DayZ page or call DayZ endpoints.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const script = fs.readFileSync(process.env.CAPIVARA_DAYZ_SCRIPT || path.join(root, "dashboard/web/customer-dayz.js"), "utf8");
const overviewScript = fs.readFileSync(process.env.CAPIVARA_MAIN_SCRIPT || path.join(root, "dashboard/web/customer-instance-v2.js"), "utf8");
assert(overviewScript.includes("window.CapivaraInstanceDayz?.configure?.(overview)"));
function fixture(initial, responseStatus = 503) {
  const nodes = {}, counts = {fetch: 0, tabs: 0};
  const nav = {querySelector: () => null, insertBefore(el) { nodes[el.id] = el; counts.tabs++; }};
  const main = {insertBefore(el) { nodes[el.id] = el; }};
  const document = {
    getElementById: id => nodes[id] || null,
    querySelector: q => q === ".sidebar nav" ? nav : q === "main" ? main : null,
    createElement: tag => ({
      tag, dataset: {}, children: [], classList: {contains: () => false},
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      remove() { delete nodes[this.id]; },
    }),
  };
  const window = {
    CapivaraCustomerInstanceOverview: initial,
    addEventListener() {},
  };
  const context = {window, document, URLSearchParams, location: {search: "?instance_id=instance-one"},
    fetch: async () => {counts.fetch++; return {ok: false, status: responseStatus, json: async () => ({error: "test failure"})};},
    setInterval() {}, clearTimeout() {}, setTimeout() {}};
  vm.runInNewContext(script, context, {filename: "customer-dayz.js"});
  return {window, nodes, counts};
}
async function test() {
  const minecraft=fixture({instance:{id:"instance-one",game_id:"minecraft"}});
  await Promise.resolve();
  assert.equal(minecraft.counts.tabs,0,"Minecraft must not show DayZ tab");
  assert.equal(minecraft.counts.fetch,0,"Minecraft must not request DayZ API");
  const palworld=fixture({instance:{id:"instance-one",game_id:"palworld"}});
  assert.equal(palworld.counts.tabs,0);
  assert.equal(palworld.counts.fetch,0);
  const waiting=fixture(null);
  assert.equal(waiting.counts.fetch,0,"wait for authenticated overview");
  waiting.window.CapivaraInstanceDayz.configure({instance:{id:"another-instance",game_id:"dayz"}});
  assert.equal(waiting.counts.fetch,0,"never accept another instance");
  waiting.window.CapivaraInstanceDayz.configure({instance:{id:"instance-one",game_id:"minecraft"}});
  assert.equal(waiting.counts.fetch,0);
  waiting.window.CapivaraInstanceDayz.configure({instance:{id:"instance-one",game_id:"DaYz"}});
  assert.equal(waiting.counts.tabs,1);
  assert.equal(waiting.counts.fetch,1);
  waiting.window.CapivaraInstanceDayz.configure({instance:{id:"instance-one",game_id:"dayz"}});
  assert.equal(waiting.counts.tabs,1,"refresh must not duplicate tab");
  const notFound=fixture({instance:{id:"instance-one",game_id:"dayz"}},404);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(notFound.nodes["dayz-tab"],"404 must not hide Mundo & Mapa");
  const view=notFound.nodes["view-dayz"];
  assert.ok(view&&view.children.length===1,"show a persistent API error panel");
  const card=view.children[0];
  assert.equal(card.children[0].textContent,"Mundo & Mapa indisponível");
  assert.ok(card.children[1].textContent.includes("HTTP 404"));
  assert.equal(card.children[2].textContent,"Tentar novamente");
  card.children[2].onclick();
  assert.equal(notFound.counts.fetch,2,"retry must refetch the API");
  waiting.window.CapivaraInstanceDayz.configure({instance:{id:"instance-one",game_id:"minecraft"}});
  assert.equal(waiting.nodes["dayz-tab"],undefined,"remove tab when game changes");
  assert.equal(waiting.nodes["view-dayz"],undefined,"remove DayZ view when game changes");
  console.log("PASS: Minecraft, Palworld, pending overview, wrong ID, DayZ, 404 retry and cleanup");
}
test().catch(e => {console.error(e); process.exitCode=1;});
