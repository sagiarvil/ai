'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function setup({build = 'local-ui-v9', reply, delayChat = false, mobile = false} = {}) {
  class Element {
    constructor() { this.children = []; this.style = {}; this.value = ''; this.textContent = ''; }
    appendChild(child) { this.children.push(child); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener() {}
    focus() {}
    remove() {}
    setAttribute(name, value) { this[name] = value; }
    contains(target) { return this === target || this.children.includes(target); }
    insertAdjacentHTML(position, html) { this.restoredHTML = html; }
  }
  const elements = Object.fromEntries(
    ['feed', 'promptInput', 'sendBtn', 'sysStatus', 'welcomeMsg', 'toolsMenu', 'toolsMenuButton']
      .map(id => [id, new Element()]));
  const classes = new Set();
  const body = {classList: {
    toggle: name => classes.has(name) ? classes.delete(name) : classes.add(name),
    contains: name => classes.has(name),
    remove: name => classes.delete(name)
  }};
  const requests = [];
  const session = new Map();
  let resolveChat;
  const context = vm.createContext({
    document: {
      getElementById: id => elements[id], createElement: () => new Element(),
      body, querySelectorAll: () => [], addEventListener() {}
    },
    matchMedia: () => ({matches: mobile}),
    location: {host: '127.0.0.1:5053'},
    AbortSignal: {timeout: () => ({})},
    performance: {now: () => 0},
    crypto: {randomUUID: () => 'unique'},
    setInterval: () => 1, clearInterval() {}, setTimeout,
    localStorage: {getItem: key => session.get(key) || null, setItem: (key,value) => session.set(key,value), removeItem: key => session.delete(key)},
    fetch: async (url, options) => {
      requests.push({url, options});
      if (url === '/api/engine_info') return {
        ok: true, json: async () => ({
          build, engine_protocol: 'baris-execution-v2', tool_loop: true})};
      if (url === '/api/tasks') {
        if (delayChat) await new Promise(resolve => { resolveChat = resolve; });
        return {ok: true, json: async () => ({task_id: 'job_test'})};
      }
      if (url.startsWith('/api/tasks/')) return {ok: true, json: async () => ({
        id: 'job_test', status: 'UNVERIFIED', created: Date.now()/1000,
        events: [], result: reply || ({engine_protocol:'baris-execution-v2', build:'local-ui-v9',
          status:'UNVERIFIED', verified:false, execution_steps:[], reply:'<script>untrusted</script>'})
      })};
      return {ok: true, json: async () => reply || ({
        engine_protocol: 'baris-execution-v2', build: 'local-ui-v9',
        status: 'UNVERIFIED', verified: false, execution_steps: [],
        reply: '<script>untrusted</script>'
      })};
    }
  });
  vm.runInContext(fs.readFileSync('public/app.js', 'utf8'), context);
  return {context, elements, requests, classes, resolve: () => resolveChat()};
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('mismatched backend disables submission', async () => {
  const app = setup({build: 'old'});
  await tick();
  assert.equal(app.elements.sendBtn.disabled, true);
  app.elements.promptInput.value = 'Yaz';
  await app.context.sendAction();
  assert.equal(app.requests.filter(r => r.url === '/api/tasks').length, 0);
});

test('file test sends exact acceptance to same-origin endpoint', async () => {
  const app = setup();
  await tick();
  app.context.testFileWrite();
  await tick();
  const chat = app.requests.find(r => r.url === '/api/tasks');
  const payload = JSON.parse(chat.options.body);
  assert.deepEqual(payload.expected_files, {
    'kabul_deneme/arayuz_unique.txt': 'Merhaba Barış'
  });
  const box = app.elements.feed.children[1];
  assert.equal(box.children[1].textContent, '<script>untrusted</script>');
});

test('model verified flag without independent acceptance is not success', async () => {
  const app = setup({reply: {
    engine_protocol: 'baris-execution-v2', build: 'local-ui-v9',
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
  assert.equal(app.requests.filter(r => r.url === '/api/tasks').length, 1);
  app.resolve();
  await first;
});


test('desktop sidebar collapses and expands', async () => {
  const app = setup();
  await tick();
  app.context.toggleSidebar();
  assert.equal(app.classes.has('sidebar-collapsed'), true);
  app.context.toggleSidebar();
  assert.equal(app.classes.has('sidebar-collapsed'), false);
});

test('mobile sidebar overlays instead of shrinking workspace', async () => {
  const app = setup({mobile: true});
  await tick();
  app.context.toggleSidebar();
  assert.equal(app.classes.has('mobile-sidebar-open'), true);
  assert.equal(app.classes.has('sidebar-collapsed'), false);
});

test('new chat clears finished messages without network request', async () => {
  const app = setup();
  await tick();
  app.elements.feed.children.push({});
  const before = app.requests.length;
  app.context.newConversation();
  assert.equal(app.elements.feed.children.length, 0);
  assert.equal(app.requests.length, before);
});

test('new chat does not hide an active task', async () => {
  const app = setup({delayChat: true});
  await tick();
  app.elements.promptInput.value = 'Yaz';
  const pending = app.context.sendAction();
  await tick();
  app.context.newConversation();
  assert.equal(app.elements.feed.children.length, 2);
  app.resolve();
  await pending;
});



test('previous-build terminal result is readable after upgrade', async () => {
  const app = setup({reply: {
    engine_protocol: 'baris-execution-v2', build: 'local-ui-v5',
    status: 'FAILED', verified: false, execution_steps: [], reply: 'Eski görev zaman aşımına uğradı.'
  }});
  await tick();
  app.elements.promptInput.value = 'Görev';
  await app.context.sendAction();
  const box = app.elements.feed.children.at(-1);
  assert.equal(box.children[0].textContent, 'GÖREV BAŞARISIZ');
  assert.equal(box.children[1].textContent, 'Eski görev zaman aşımına uğradı.');
  assert.equal(app.requests.filter(r => r.url.startsWith('/api/tasks/')).length, 1);
});


test('activity distinguishes recent progress, stalled telemetry, queue and terminal state', () => {
  const app = setup();
  const job = {status:'RUNNING', created:900, latest_event:{kind:'MODEL_PROGRESS',at:999}};
  assert.equal(app.context.activityState(job,1000).label,'Model üretiyor');
  assert.equal(app.context.activityState(job,1020).mode,'waiting');
  assert.match(app.context.activityState(job,1100).label,/durduğu doğrulanmadı/);
  assert.equal(app.context.activityState({...job,status:'QUEUED'},1100).mode,'queued');
  assert.equal(app.context.activityState({...job,status:'FAILED'},1100).mode,'finished');
  assert.equal(app.context.activityState({...job,latest_event:{kind:'MODEL_START',at:1000}},1000).label,'Model yanıtı bekleniyor');
});


test('task timing separates wall time from the remaining execution budget', () => {
  const app = setup();
  const label = app.context.taskTiming({created:Date.now()/1000-40,used:12.2,budget_seconds:900,remaining_seconds:887.8}, 'job_t');
  assert.match(label, /Çalışma bütçesi 13\/900 sn/);
  assert.match(label, /Kalan 888 sn/);
});

test('exact file acceptance does not claim that all program behavior passed', async () => {
  const app = setup({reply: {
    engine_protocol:'baris-execution-v2', build:'local-ui-v9', status:'VERIFIED', verified:true,
    execution_steps:[{tool:'write',success:true}], acceptance:{success:true},
    verification_scope:'exact_files'
  }});
  await tick();
  app.elements.promptInput.value = 'Dosyayı oluştur';
  await app.context.sendAction();
  assert.equal(app.elements.feed.children.at(-1).children[0].textContent, 'DOSYA KABULÜ DOĞRULANDI');
});
