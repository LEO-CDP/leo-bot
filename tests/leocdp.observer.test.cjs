const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(
  path.join(__dirname, "../resources/js/leocdp.observer.js"),
  "utf8"
);

test("queues Google login tracking until the observer SDK is ready", () => {
  const scriptNode = { parentNode: { insertBefore() {} } };
  const loginEvents = [];
  const context = vm.createContext({
    window: {},
    location: { href: "https://leobot.test/" },
    encodeURIComponent,
    document: {
      title: "LEO",
      createElement() {
        return {};
      },
      getElementsByTagName() {
        return [scriptNode];
      },
    },
  });

  vm.runInContext(source, context);
  context.trackEventLogin({ name: "Ada Lovelace", email: "ada@example.com" });
  assert.equal(context.window.leoPendingLoginEvents.length, 1);

  context.window.LeoObserver = {
    recordEventPageView() {},
    recordEventLogin(eventData) {
      loginEvents.push(eventData);
    },
  };
  context.leoObserverProxyReady();

  assert.equal(loginEvents.length, 1);
  assert.equal(loginEvents[0].name, "Ada Lovelace");
  assert.equal(loginEvents[0].email, "ada@example.com");
  assert.equal(context.window.leoPendingLoginEvents.length, 0);
});
