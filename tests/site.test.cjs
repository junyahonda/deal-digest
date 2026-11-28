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

test("category filters show up to five recent deals in rank order and report shortages", async () => {
  const page = readFileSync("index.html", "utf8");
  const buttons = Array.from(page.matchAll(/<button[^>]*data-category="([^"]+)" aria-pressed="([^"]+)"[^>]*>/g),
    ([, category, pressed]) => ({
      dataset: { category }, pressed, disabled: true,
      addEventListener(type, fn) { assert.equal(type, "click"); this.click = fn; },
      setAttribute(name, value) { assert.equal(name, "aria-pressed"); this.pressed = value; },
    }));
  assert.deepEqual(buttons.map((button) => [button.dataset.category, button.pressed]),
    [["all", "true"], ["giftcards", "false"], ["tech", "false"], ["games", "false"], ["other", "false"]]);

  let cards;
  const status = {};
  const selectors = {
    "#deals": { replaceChildren(...children) { cards = children; } },
    "#status": status,
    "#updated": { replaceChildren() {} },
    "#deal-template": { content: { cloneNode() {
      const elements = new Map();
      return { querySelector(selector) {
        if (!elements.has(selector)) elements.set(selector, { hidden: true, setAttribute() {} });
        return elements.get(selector);
      } };
    } } },
  };
  const now = Date.parse("2026-11-25T20:00:00Z");
  const deal = (title, category, hours = 1) => ({
    title, category, votes: 0, views: 0, comments: 0, score: 0,
    posted_at: new Date(now - hours * 3600000).toISOString(),
  });
  const tech = Array.from({ length: 6 }, (_, n) => deal(`tech ${n + 1}`, "tech"));
  runInNewContext(readFileSync("app.js", "utf8"), {
    document: { querySelector: (selector) => selectors[selector], querySelectorAll: () => buttons,
      createElement: () => ({}) },
    Date: class extends Date { static now() { return now; } },
    fetch: async () => ({ ok: true, async json() {
      return { generated_at: new Date(now).toISOString(), deals: [
        deal("expired", "tech", 25), deal("gift", "giftcards"), ...tech,
        deal("Switch 2", "games"), deal("future", "other", -1),
      ] };
    } }),
    navigator: {},
  });
  await new Promise(setImmediate);

  const titles = () => cards.map((card) => card.querySelector(".deal-title").textContent);
  assert.ok(buttons.every((button) => !button.disabled));
  assert.deepEqual(titles(), ["gift", "tech 1", "tech 2", "tech 3", "tech 4"]);
  const [, giftcards, techFilter, games, other] = buttons;
  techFilter.click();
  assert.deepEqual(titles(), ["tech 1", "tech 2", "tech 3", "tech 4", "tech 5"]);
  assert.deepEqual(buttons.map((button) => button.pressed), ["false", "false", "true", "false", "false"]);
  assert.equal(cards[0].querySelector(".place").textContent, "#1");
  assert.equal(cards[0].querySelector(".deal-category").textContent, "Tech");
  assert.equal(cards[0].querySelector(".deal-category").hidden, false);
  assert.equal(status.hidden, true);
  giftcards.click();
  assert.deepEqual(titles(), ["gift"]);
  assert.match(status.textContent, /Only 1 deal in this category/);
  games.click();
  assert.deepEqual(titles(), ["Switch 2"]);
  assert.equal(cards[0].querySelector(".deal-category").textContent, "Switch 2 & PC games");
  other.click();
  assert.deepEqual(titles(), []);
  assert.match(status.textContent, /No deals in this category/);
  buttons[0].click();
  assert.deepEqual(titles(), ["gift", "tech 1", "tech 2", "tech 3", "tech 4"]);
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
