const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

test("the ranking explanation is plain content and does not need a disclosure", () => {
  const page = readFileSync("index.html", "utf8");
  const explanation = page.match(/<section\b[^>]*aria-labelledby="ranking-help-title"[^>]*>([\s\S]*?)<\/section>/);
  assert.ok(explanation);
  assert.match(explanation[1], /<h2 id="ranking-help-title">How the ranking works<\/h2>/);
  assert.match(explanation[1], /without drowning out votes and discussion/);
  assert.doesNotMatch(page, /<details\b/);
});

test("the offline worker refreshes the scoped digest from the network before falling back", async () => {
  const scope = "https://example.test/deal-digest/";
  const data = `${scope}data/deals.json`;
  const entries = new Map();
  const cache = { put: (key, value) => Promise.resolve(entries.set(key, value)),
    match: (key) => entries.get(key) };
  let fetchEvent;
  let online = true;
  runInNewContext(readFileSync("sw.js", "utf8"), {
    self: { registration: { scope }, addEventListener: (type, fn) => {
      if (type === "fetch") fetchEvent = fn;
    } },
    caches: { open: () => cache }, URL, Response,
    fetch: () => {
      if (!online) throw new Error("Offline");
      return new Response("fresh");
    },
  });

  function request(url) {
    return new Promise((respondWith) => fetchEvent({ request: { url, method: "GET" }, respondWith }));
  }
  entries.set(data, new Response("old"));
  assert.equal(await (await request(data)).text(), "fresh");
  online = false;
  assert.equal(await (await request(data)).text(), "fresh");
  entries.set(scope, new Response("app shell"));
  assert.equal(await (await request(`${scope}index.html`)).text(), "app shell");
});
