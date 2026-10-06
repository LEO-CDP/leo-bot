const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(
  path.join(__dirname, "../resources/js/leocdp.chatbot.js"),
  "utf8"
);

function setupChat() {
  const requests = [];
  const answers = [];
  const errors = [];
  const removedLoaders = [];
  const cache = new Map();
  let promptCount = 0;

  function jquery() {
    return {
      find() { return this; },
      slice() { return this; },
      map() { return this; },
      get() { return ["Previous conversation"]; },
    };
  }
  jquery.ajax = options => {
    const request = { options };
    requests.push(request);
    return {
      done(callback) {
        request.success = callback;
        return this;
      },
    };
  };

  const context = vm.createContext({
    window: { addEventListener() {} },
    console: { log() {}, info() {}, warn() {}, error() {} },
    $: jquery,
    BASE_URL_LEOBOT: "/_leoai/ask",
    CDP_TRACKING: false,
    lscache: { set(key, value) { cache.set(key, value); } },
  });
  vm.runInContext(source, context);
  context.currentUserProfile.visitorId = "visitor";
  context.currentUserProfile.touchpointId = "tp";
  context.currentUserProfile.latitude = 10.747904;
  context.currentUserProfile.longitude = 106.6467328;
  context.showChatBotLoader = () => Promise.resolve(7);
  context.getBotUI = () => ({
    message: { remove(index) { removedLoaders.push(index); } },
  });
  context.leoBotShowAnswer = answer => answers.push(answer);
  context.leoBotPromptQuestion = () => { promptCount += 1; };
  context.leoBotShowError = (message, nextAction) => {
    errors.push(message);
    nextAction();
  };
  return {
    context, requests, answers, errors, removedLoaders, cache,
    promptCount: () => promptCount,
  };
}

for (const choice of ["1", "2", "3", "4", "5", " 4 "]) {
  test(`sends single-digit place selection ${JSON.stringify(choice)}`, async () => {
    const chat = setupChat();
    chat.context.sendQuestionToLeoAI("ask", choice);
    await Promise.resolve();

    assert.equal(chat.requests.length, 1);
    const request = chat.requests[0];
    assert.equal(request.options.url, "/_leoai/ask");
    const payload = JSON.parse(request.options.data);
    assert.equal(payload.question, choice.trim());
    assert.equal(payload.visitor_id, "visitor");
    assert.equal(payload.touchpoint_id, "tp");
    assert.equal(payload.latitude, 10.747904);
    assert.equal(payload.longitude, 106.6467328);
    assert.equal(payload.answer_in_format, "html");

    const confirmation = "<p>Bạn đã chọn <strong>Cha Tam Church</strong>.</p>";
    request.success({ error_code: 0, answer: confirmation, touchpoint_id: "tp" });
    assert.deepEqual(chat.answers, [confirmation]);
    assert.deepEqual(chat.removedLoaders, [7]);
  });
}

test("continues sending normal questions", async () => {
  const chat = setupChat();
  chat.context.sendQuestionToLeoAI("ask", "  Tell me about this church  ");
  await Promise.resolve();
  assert.equal(
    JSON.parse(chat.requests[0].options.data).question,
    "Tell me about this church"
  );
});

test("blank input shows feedback and restores the question prompt", async () => {
  const chat = setupChat();
  chat.context.sendQuestionToLeoAI("ask", "   ");
  await Promise.resolve();
  assert.equal(chat.requests.length, 0);
  assert.equal(chat.errors.length, 1);
  assert.equal(chat.promptCount(), 1);
});

test("exit remains local and is not sent to the API", async () => {
  const chat = setupChat();
  chat.context.sendQuestionToLeoAI("ask", "exit");
  await Promise.resolve();
  assert.equal(chat.requests.length, 0);
});

test("failed selection request clears its loader and restores the prompt", async () => {
  const chat = setupChat();
  chat.context.sendQuestionToLeoAI("ask", "4");
  await Promise.resolve();
  chat.requests[0].options.error({}, "network error");
  assert.deepEqual(chat.removedLoaders, [7]);
  assert.equal(chat.errors.length, 1);
  assert.equal(chat.promptCount(), 1);
});
