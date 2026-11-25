const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

function setupRankingHelp() {
  const callbacks = {};
  const events = { addEventListener: (type, fn) => { callbacks[type] = fn; } };
  const help = { ...events, querySelector: () => events };
  const stack = [null];
  const history = {
    get state() { return stack.at(-1); },
    pushState: (entry) => stack.push(entry),
    back: () => {
      assert.equal(stack.length, 2);
      stack.pop();
      callbacks.popstate();
    },
  };
  runInNewContext(readFileSync("app.js", "utf8"), {
    document: { querySelector: () => help },
    window: events, history, navigator: {},
    fetch: () => new Promise(() => {}),
  });

  const tap = () => callbacks.click({ preventDefault() {} });
  return { help, stack, history, tap, toggle: () => callbacks.toggle() };
}

test("ranking help opens one history entry and closes on Back or a second tap", () => {
  const { help, stack, history, tap, toggle } = setupRankingHelp();
  tap();
  toggle();
  assert.equal(help.open, true);
  assert.equal(stack.length, 2);
  history.back();
  assert.equal(help.open, false);
  tap();
  tap();
  assert.equal(help.open, false);
  assert.equal(stack.length, 1);
});

test("tapping ranking help opened by Find in Page closes it without navigating", () => {
  const { help, stack, tap } = setupRankingHelp();
  help.open = true;
  tap();
  assert.equal(help.open, false);
  assert.equal(stack.length, 1);
  tap();
  assert.equal(help.open, true);
  assert.equal(stack.length, 2);
});

test("Find in Page opening creates one entry that Back or a tap can close", () => {
  const { help, stack, history, tap, toggle } = setupRankingHelp();
  help.open = true;
  toggle();
  toggle();
  assert.equal(stack.length, 2);
  history.back();
  toggle();
  assert.equal(help.open, false);
  assert.equal(stack.length, 1);

  help.open = true;
  toggle();
  tap();
  toggle();
  assert.equal(help.open, false);
  assert.equal(stack.length, 1);
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
