// Isolated browser-like contract: generic DayZ map registration never changes the active mission.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../dashboard/web/customer-dayz.js"), "utf8");

class FakeElement {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
    this._value = "";
    this.disabled = false;
    this.textContent = "";
    this.listeners = {};
    this.id = "";
    this.files = [];
  }
  get value() { return this._value; }
  set value(v) { this._value = String(v); }
  append(...nodes) {
    for (const node of nodes) {
      if (node == null) continue;
      this.children.push(node);
      node.parentNode = this;
      if (this.tagName === "SELECT" && this.children.length === 1) this.value = node.value;
    }
  }
  add(node) { this.append(node); }
  appendChild(node) { this.append(node); return node; }
  insertBefore(node, anchor) {
    if (!anchor || !this.children.includes(anchor)) return this.append(node);
    this.children.splice(this.children.indexOf(anchor), 0, node);
    node.parentNode = this;
  }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  dispatch(name) { this.listeners[name]?.(); }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(v => v !== this);
  }
  find(id) {
    if (this.id === id) return this;
    for (const child of this.children) {
      if (typeof child.find === "function") {
        const found = child.find(id);
        if (found) return found;
      }
    }
    return null;
  }
  contains(other) { return this === other || this.children.some(c => c === other || c.contains?.(other)); }
}
class FakeOption extends FakeElement {
  constructor(label, value) {
    super("option");
    this.textContent = label;
    this.value = value;
  }
}
function fixture({permissions = ["content.install", "instance.restart", "settings.write"],
                  mods = true, workshop = true, upload = true} = {}) {
  const nav = new FakeElement("nav"), main = new FakeElement("main"), toast = new FakeElement("div");
  toast.id = "toast";
  const posted = [];
  const overview = {
    instance: {id: "test-dayz-001", game_id: "dayz"},
    permissions,
    content_policy: {mods_allowed: mods, workshop_allowed: workshop, external_upload_allowed: upload},
  };
  const document = {
    activeElement: null,
    getElementById(id) { return nav.find(id) || main.find(id) || toast.find(id); },
    querySelector(selector) {
      if (selector === ".sidebar nav") return nav;
      if (selector === "main") return main;
      return null;
    },
    querySelectorAll() { return []; },
    createElement(tag) { return new FakeElement(tag); },
    createTextNode(text) { const n = new FakeElement("#text"); n.textContent = text; return n; },
  };
  const fetch = async (url, options = {}) => {
    if (options.method === "POST") {
      posted.push({url, body: JSON.parse(options.body)});
      return {ok: true, status: 202, json: async () => ({operation: {operation_id: "queued"}})};
    }
    return {ok: true, status: 200, json: async () => ({
      instance_id: "test-dayz-001", editable: true, maps: {missions: [], counts: {available: 0, installed: 0}},
      operations: [],
    })};
  };
  const context = {
    window: {CapivaraCustomerInstanceOverview: overview, addEventListener() {}},
    document, location: {search: "?instance_id=test-dayz-001"},
    URLSearchParams, Option: FakeOption, fetch,
    setInterval() {}, setTimeout() {}, clearTimeout() {},
    confirm() { throw Error("Map switch must require a separate explicit confirmation"); },
  };
  vm.runInNewContext(script, context, {filename: "customer-dayz.js"});
  return {document, posted, node: id => document.getElementById(id)};
}
async function loaded(f) {
  for (let i = 0; i < 5 && !f.node("dayz-community-map-name"); i++) await Promise.resolve();
  assert.ok(f.node("dayz-community-map-name"), "DayZ community map form must render");
}
async function testAllMissionsFromGithub() {
  const f = fixture();
  await loaded(f);
  const name = f.node("dayz-community-map-name"), repo = f.node("dayz-community-map-repository");
  const scope = f.node("dayz-community-map-mission-scope");
  const workshop = f.node("dayz-community-map-workshop");
  const button = f.node("dayz-community-map-mission-help").parentNode.children.find(c => c.textContent === "Adicionar / reparar mapa");
  assert.ok(button, "Install button must be available");
  assert.equal(scope.value, "all");
  assert.equal(f.node("dayz-community-map-mission-path").parentNode.style.display, "none");
  name.value = "Ilha Teste Ágora";
  repo.value = "example/project";
  workshop.value = "123456 987654";
  workshop.dispatch("input");
  assert.equal(button.disabled, false);
  await button.onclick();
  assert.equal(f.posted.length, 1);
  assert.equal(f.posted[0].url, "/api/customer/instance/dayz/community-map");
  const body = f.posted[0].body;
  assert.equal(body.instance_id, "test-dayz-001");
  assert.equal(body.name, "Ilha Teste Ágora");
  assert.equal(body.content_id, "dayz-map:ilha-teste-agora");
  assert.equal(body.mission_path, "");
  assert.deepEqual(Array.from(body.workshop_items), ["123456", "987654"]);
  assert.equal(body.source.provider, "github");
  assert.equal(body.source.repository, "example/project");
  assert.ok(f.posted.every(p => p.body.action !== "change_mission"), "Registering map must not switch active mission");
}
async function testSingleMissionFromHttps() {
  const f = fixture();
  await loaded(f);
  const scope = f.node("dayz-community-map-mission-scope");
  const name = f.node("dayz-community-map-name"), provider = f.node("dayz-community-map-provider");
  const missionPath = f.node("dayz-community-map-mission-path");
  const url = f.node("dayz-community-map-url");
  const button = f.node("dayz-community-map-mission-help").parentNode.children.find(c => c.textContent === "Adicionar / reparar mapa");
  scope.value = "single"; scope.onchange();
  assert.equal(missionPath.parentNode.style.display, "");
  name.value = "Mapa B"; provider.value = "http-archive"; provider.onchange();
  url.value = "https://example.org/map.zip";
  await button.onclick();
  assert.equal(f.posted.length, 0, "An empty selected mission path must block submission");
  missionPath.value = "Mission Files/hardcore.example";
  await button.onclick();
  assert.equal(f.posted.length, 1);
  assert.equal(f.posted[0].body.source.provider, "http-archive");
  assert.equal(f.posted[0].body.source.url, "https://example.org/map.zip");
  assert.equal(f.posted[0].body.mission_path, "Mission Files/hardcore.example");
}
async function testEffectiveContractGates() {
  const denied = fixture({permissions: ["instance.restart", "settings.write"]});
  await loaded(denied);
  const deniedButton = denied.node("dayz-community-map-mission-help").parentNode.children.find(c => c.textContent === "Adicionar / reparar mapa");
  assert.equal(deniedButton.disabled, true);
  await deniedButton.onclick();
  assert.equal(denied.posted.length, 0);
  const mapDisallowed = fixture({mods: false});
  await loaded(mapDisallowed);
  const blocked = mapDisallowed.node("dayz-community-map-mission-help").parentNode.children.find(c => c.textContent === "Adicionar / reparar mapa");
  assert.equal(blocked.disabled, true);
  const noWorkshop = fixture({workshop: false});
  await loaded(noWorkshop);
  const without = noWorkshop.node("dayz-community-map-mission-help").parentNode.children.find(c => c.textContent === "Adicionar / reparar mapa");
  assert.equal(without.disabled, false, "No workshop dependencies should not require workshop permission");
  const item = noWorkshop.node("dayz-community-map-workshop");
  item.value = "4321"; item.dispatch("input");
  assert.equal(without.disabled, true);
  item.value = ""; item.dispatch("input");
  assert.equal(without.disabled, false);
  const noUpload = fixture({upload: false});
  await loaded(noUpload);
  const uploadButton = noUpload.node("dayz-community-map-mission-help").parentNode.children.find(c => c.textContent === "Adicionar / reparar mapa");
  const provider = noUpload.node("dayz-community-map-provider");
  provider.value = "upload"; provider.onchange();
  assert.equal(uploadButton.disabled, true);
  provider.value = "github"; provider.onchange();
  assert.equal(uploadButton.disabled, false);
}
(async () => {
  await testAllMissionsFromGithub();
  await testSingleMissionFromHttps();
  await testEffectiveContractGates();
  console.log("PASS generic DayZ map form: GitHub/all missions, HTTPS/specific mission, entitlements, no restart");
})().catch(error => { console.error(error); process.exitCode = 1; });
