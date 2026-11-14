#!/usr/bin/env node
// Regression coverage for late Agent replies and deduplicated file listings.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const web = path.join(__dirname, "..", "dashboard", "web");

async function testPolling(filename) {
  const source = fs.readFileSync(path.join(web, filename), "utf8");
  const declaration = source.split("\n").find(line => line.startsWith("async function waitAgentCommandStatus("));
  assert.ok(declaration, filename + " must define the polling helper");
  let now = 0;
  let replies = [];
  let requests = 0;
  const request = async () => { requests++; return replies.shift() || {status:"pending"}; };
  const setTimeout = callback => { now += 100; callback(); };
  const Date = {now: () => now};
  const wait = new Function("request", "setTimeout", "Date", "iid",
    declaration + "; return waitAgentCommandStatus;")(request, setTimeout, Date, "instance-test");
  replies = [{status:"pending"}, {status:"completed", result:{entries:[]}}];
  assert.equal((await wait("/status", "command-1", {intervalMs:100, maxWaitMs:1000})).status, "completed");
  assert.equal(requests, 2);
  replies = [{status:"failed", last_error:"agent failed"}];
  await assert.rejects(wait("/status", "command-2", {intervalMs:100, maxWaitMs:1000}), /agent failed/);
  replies = [];
  await assert.rejects(wait("/status", "command-3", {intervalMs:100, maxWaitMs:200}), /sem confirmação/);
  await assert.rejects(wait("/status", "", {intervalMs:100, maxWaitMs:1000}), /identificador/);
}

async function testListCoalescing() {
  const source = fs.readFileSync(path.join(web, "customer-instance-v2.js"), "utf8");
  const declaration = source.split("\n").find(line => line.startsWith("const pendingFileLists=new Map();async function fileCommand("));
  assert.ok(declaration, "file listing deduplication must be present");
  let enqueued = 0;
  const request = async () => ({command_id:"command-" + ++enqueued});
  const waitAgentCommandStatus = async () => ({status:"completed", result:{entries:[]}});
  const fileCommand = new Function("request", "waitAgentCommandStatus", "api", "iid", "filePath",
    declaration + "; return fileCommand;")(request, waitAgentCommandStatus, "/api", "instance-test", ".");
  await Promise.all([fileCommand("list", "."), fileCommand("list", ".")]);
  assert.equal(enqueued, 1, "same-folder concurrent listings should share a command");
  await Promise.all([fileCommand("write_text", "a", null, {content:"one"}), fileCommand("write_text", "a", null, {content:"two"})]);
  assert.equal(enqueued, 3, "writes must not be deduplicated");
  await fileCommand("list", ".");
  assert.equal(enqueued, 4, "a finished listing may be requested again");
}

(async () => {
  await testPolling("customer-instance-v2.js");
  await testPolling("controller-instance-core.js");
  await testListCoalescing();
  console.log("Agent async polling and list deduplication: PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
