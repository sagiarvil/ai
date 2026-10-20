'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function setup({build = 'local-ui-v4', reply, delayChat = false} = {}) {
  class Element {
    constructor() { this.children = []; this.style = {}; this.value = ''; this.textContent = ''; }
    appendChild(child) { this.children.push(child); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener() {}
    focus() {}
    remove() {}
  }
  const elements = Object.fromEntries(
    ['feed', 'promptInput', 'sendBtn', 'sysStatus', 'welcomeMsg']
      .map(id => [id, new Element()]));
  const requests = [];
  let resolveChat;
  const context = vm.createContext({
    document: {getElementById: id => elements[id], createElement: () => new Element()},
    location: {host: '127.0.0.1:5053'},
    AbortSignal: {timeout: () => ({})},
    performance: {now: () => 0},
    crypto: {randomUUID: () => 'unique'},
    setInterval: () => 1, clearInterval() {},
    fetch: async (url, options) => {
      requests.push({url, options});
      if (url === '/api/engine_info') return {
        ok: true, json: async () => ({
          build, engine_protocol: 'baris-execution-v2', tool_loop: true})};
      if (delayChat) await new Promise(resolve => { resolveChat = resolve; });
      return {ok: true, json: async () => reply || ({
        engine_protocol: 'baris-execution-v2', build: 'local-ui-v4',
        status: 'UNVERIFIED', verified: false, execution_steps: [],
        reply: '<script>untrusted</script>'
      })};
    }
  });
  vm.runInContext(fs.readFileSync('public/app.js', 'utf8'), context);
  return {context, elements, requests, resolve: () => resolveChat()};
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('mismatched backend disables submission', async () => {
  const app = setup({build: 'old'});
  await tick();
  assert.equal(app.elements.sendBtn.disabled, true);
  app.elements.promptInput.value = 'Yaz';
  await app.context.sendAction();
  assert.equal(app.requests.filter(r => r.url === '/api/chat').length, 0);
});

test('file test sends exact acceptance to same-origin endpoint', async () => {
  const app = setup();
  await tick();
  app.context.testFileWrite();
  await tick();
  const chat = app.requests.find(r => r.url === '/api/chat');
  const payload = JSON.parse(chat.options.body);
  assert.deepEqual(payload.expected_files, {
    'kabul_deneme/arayuz_unique.txt': 'Merhaba Barış'
  });
  const box = app.elements.feed.children[1];
  assert.equal(box.children[1].textContent, '<script>untrusted</script>');
});

test('model verified flag without independent acceptance is not success', async () => {
  const app = setup({reply: {
    engine_protocol: 'baris-execution-v2', build: 'local-ui-v4',
    status: 'VERIFIED', verified: true,
    execution_steps: [{tool: 'write', success: true}], acceptance: null
  }});
  await tick();
  app.elements.promptInput.value = 'Yaz';
  await app.context.sendAction();
  assert.equal(app.elements.feed.children[1].children[0].textContent,
               'İŞLEM VAR; SONUÇ DOĞRULANMADI');
});

test('double submission produces only one request', async () => {
  const app = setup({delayChat: true});
  await tick();
  app.elements.promptInput.value = 'Yaz';
  const first = app.context.sendAction();
  await tick();
  await app.context.sendAction();
  assert.equal(app.requests.filter(r => r.url === '/api/chat').length, 1);
  app.resolve();
  await first;
});
