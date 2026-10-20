'use strict';
const feed = document.getElementById('feed');
const input = document.getElementById('promptInput');
const sendBtn = document.getElementById('sendBtn');
const statusLabel = document.getElementById('sysStatus');
let busy = false;
let connected = false;

function quickFill(text) { input.value = text; input.focus(); }

async function engineInfo() {
  const response = await fetch('/api/engine_info', {
    cache: 'no-store', signal: AbortSignal.timeout(5000)
  });
  if (!response.ok) throw new Error('Yerel sunucuya ulaşılamadı.');
  const info = await response.json();
  if (info.engine_protocol !== 'baris-execution-v2' ||
      info.build !== 'local-ui-v5' || info.tool_loop !== true) {
    throw new Error('Arayüz ve motor sürümü uyuşmuyor.');
  }
  return info;
}

async function refreshConnection() {
  try {
    const info = await engineInfo();
    connected = true;
    statusLabel.textContent = 'Motor bağlı • ' + location.host +
      (info.busy ? ' • Görev çalışıyor' : '');
    statusLabel.style.color = '#3fb950';
  } catch (error) {
    connected = false;
    statusLabel.textContent = error.message;
    statusLabel.style.color = '#f85149';
  }
  sendBtn.disabled = busy || !connected;
}

function renderResult(box, data) {
  if (data.engine_protocol !== 'baris-execution-v2' || data.build !== 'local-ui-v5') {
    throw new Error('Yanıt beklenen motora ait değil.');
  }
  const steps = Array.isArray(data.execution_steps) ? data.execution_steps : [];
  const verified = data.status === 'VERIFIED' && data.verified === true &&
    steps.length > 0 && data.acceptance && data.acceptance.success === true;
  box.replaceChildren();
  const heading = document.createElement('strong');
  heading.textContent = verified ? 'GÖREV DOĞRULANDI' :
    (steps.length ? 'İŞLEM VAR; SONUÇ DOĞRULANMADI' : 'İŞLEM TAMAMLANMADI');
  box.appendChild(heading);
  const message = document.createElement('p');
  message.textContent = data.reply || 'İşlem açıklaması yok.';
  box.appendChild(message);
  for (const step of steps) {
    const line = document.createElement('p');
    line.textContent = (step.success ? '✓ ' : '• ') + step.tool;
    box.appendChild(line);
    if (step.result && typeof step.result.content === 'string') {
      const content = document.createElement('pre');
      content.textContent = step.result.content;
      box.appendChild(content);
    }
  }
  const evidence = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = 'İşlem kanıtları';
  const output = document.createElement('pre');
  output.textContent = JSON.stringify(data, null, 2);
  evidence.append(summary, output);
  box.appendChild(evidence);
}

async function sendAction(expectedFiles = null) {
  if (busy || !connected) return;
  if (localStorage.getItem('barisActiveTask')) { await resumeVisibleTask(); return; }
  const text = input.value.trim();
  if (!text) return;
  busy = true;
  sendBtn.disabled = true;
  input.disabled = true;
  document.getElementById('welcomeMsg')?.remove();
  const user = document.createElement('div');
  user.className = 'msg-user';
  user.textContent = text;
  const box = document.createElement('div');
  box.className = 'msg-ai';
  feed.append(user, box);
  input.value = '';
  input.style.height = 'auto';
  const started = performance.now();
  const update = () => {
    box.textContent = 'Görev çalışıyor • ' +
      Math.floor((performance.now() - started) / 1000) +
      ' saniye. Sonuç, araç kayıtlarıyla birlikte gösterilecek.';
  };
  update();
  const timer = setInterval(update, 1000);
  try {
    await engineInfo();
    const payload = {message: text};
    if (expectedFiles) payload.expected_files = expectedFiles;
    const submitted = await submitPayload(payload);
    localStorage.setItem('barisActiveTask', submitted.task_id);
    localStorage.removeItem('barisPendingSubmission');
    clearInterval(timer);
    await followTask(submitted.task_id, box);

  } catch (error) {
    clearInterval(timer);
    box.textContent = error.name === 'TimeoutError'
      ? 'Yanıt süresi doldu. Görev otomatik tekrar gönderilmedi; işlem kaydını kontrol edin.'
      : 'İşlem doğrulanamadı: ' + error.message;
  } finally {
    clearInterval(timer);
    busy = false;
    input.disabled = false;
    await refreshConnection();
    input.focus();
    feed.scrollTop = feed.scrollHeight;
  }
}

async function submitPayload(payload) {
  const previous = localStorage.getItem('barisPendingSubmission');
  const pending = previous ? JSON.parse(previous) : {key: crypto.randomUUID(), payload};
  if (previous && JSON.stringify(pending.payload) !== JSON.stringify(payload)) {
    throw new Error('Önceki gönderimin sonucu belirsiz. Sayfayı yenileyerek aynı işlem anahtarıyla kontrol et.');
  }
  localStorage.setItem('barisPendingSubmission', JSON.stringify(pending));
  const response = await fetch('/api/tasks', {
    method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': pending.key},
    body: JSON.stringify(pending.payload), signal: AbortSignal.timeout(10000)
  });
  const submitted = await response.json();
  if (!response.ok) throw new Error(typeof submitted.detail === 'string' ? submitted.detail : 'Görev alınamadı.');
  return submitted;
}
const terminalStates = new Set(['VERIFIED', 'UNVERIFIED', 'FAILED', 'CANCELLED', 'BLOCKED']);
let activeTaskId = null;
async function followTask(taskId, box) {
  activeTaskId = taskId;
  let lastSeq = 0;
  let lastMessage = 'Görev sırada bekliyor.';
  let networkErrors = 0;
  while (true) {
    try {
      const response = await fetch('/api/tasks/' + encodeURIComponent(taskId) + '?after=' + lastSeq,
        {cache: 'no-store', signal: AbortSignal.timeout(5000)});
      if (!response.ok) throw new Error('Görev durumu alınamadı.');
      const job = await response.json();
      networkErrors = 0;
      for (const event of job.events || []) {
        lastSeq = Math.max(lastSeq, event.seq);
        if (event.data.message) lastMessage = event.data.message;
        if (event.kind === 'MODEL_PROGRESS') lastMessage += ' • ' + event.data.characters + ' karakter';
      }
      box.replaceChildren();
      const message = document.createElement('p');
      message.textContent = lastMessage;
      const identity = document.createElement('p');
      identity.textContent = 'Görev: ' + taskId + ' • ' + Math.floor((Date.now()/1000) - job.created) + ' saniye';
      const cancel = document.createElement('button');
      cancel.textContent = 'Görevi durdur';
      cancel.onclick = async () => {
        cancel.disabled = true;
        try {
          const response = await fetch('/api/tasks/' + encodeURIComponent(taskId) + '/cancel', {method: 'POST'});
          if (!response.ok) throw new Error('Durdurma isteği alınamadı.');
          cancel.textContent = 'Durdurma istendi';
        } catch (error) { cancel.disabled = false; cancel.textContent = error.message; }
      };
      box.append(message, identity, cancel);
      if (job.plan && job.plan.length) {
        const plan = document.createElement('details');
        const label = document.createElement('summary'); label.textContent = 'İş planı';
        const list = document.createElement('ol');
        for (const text of job.plan) { const item = document.createElement('li'); item.textContent = text; list.appendChild(item); }
        plan.append(label, list); box.appendChild(plan);
      }
      if (terminalStates.has(job.status)) {
        if (job.result) renderResult(box, job.result);
        else message.textContent = 'Görev sonlandı: ' + job.status;
        localStorage.removeItem('barisActiveTask');
        activeTaskId = null;
        return;
      }
    } catch (error) {
      networkErrors += 1;
      box.textContent = 'Bağlantı bekleniyor; görev tekrar gönderilmiyor. Görev: ' + taskId;
      if (networkErrors >= 15) throw new Error('Bağlantı kesildi. Görev kaydı korundu; sayfayı yenileyerek izlemeye devam et.');
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}
async function resumeVisibleTask() {
  let taskId = localStorage.getItem('barisActiveTask');
  if (busy) return;
  const pending = localStorage.getItem('barisPendingSubmission');
  if (!taskId && !pending) return;
  busy = true; sendBtn.disabled = true; input.disabled = true;
  document.getElementById('welcomeMsg')?.remove();
  const box = document.createElement('div'); box.className = 'msg-ai'; feed.appendChild(box);
  try {
    if (!taskId && pending) {
      const submitted = await submitPayload(JSON.parse(pending).payload);
      taskId = submitted.task_id;
      localStorage.setItem('barisActiveTask', taskId);
      localStorage.removeItem('barisPendingSubmission');
    }
    await followTask(taskId, box);
  }
  catch (error) { box.textContent = error.message; }
  finally { busy = false; input.disabled = false; await refreshConnection(); }
}
function testFileWrite() {
  if (busy || !connected) return;
  const path = 'kabul_deneme/arayuz_' + crypto.randomUUID() + '.txt';
  input.value = 'expected_files içindeki dosyayı belirtilen içerikle birebir oluştur. Ek karakter ekleme.';
  sendAction({[path]: 'Merhaba Barış'});
}

input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendAction();
  }
});
refreshConnection();


// Layout controls do not alter the execution protocol.
const welcomeTemplate = document.getElementById('welcomeMsg')?.outerHTML || '';
function toggleSidebar() {
  const mobile = matchMedia('(max-width: 900px)').matches;
  document.body.classList.toggle(mobile ? 'mobile-sidebar-open' : 'sidebar-collapsed');
  const expanded = mobile ? document.body.classList.contains('mobile-sidebar-open') :
    !document.body.classList.contains('sidebar-collapsed');
  document.querySelectorAll('[data-menu-toggle]').forEach(button =>
    button.setAttribute('aria-expanded', String(expanded)));
}
function selectSuggestion(text) {
  quickFill(text);
  document.body.classList.remove('mobile-sidebar-open');
}
function newConversation() {
  if (busy) {
    statusLabel.textContent = 'Çalışan görev bitmeden sohbet temizlenmez.';
    return;
  }
  feed.replaceChildren();
  if (welcomeTemplate) feed.insertAdjacentHTML('beforeend', welcomeTemplate);
  input.value = '';
  input.style.height = '';
  document.body.classList.remove('mobile-sidebar-open');
  closeToolsMenu();
  input.focus();
}
function closeToolsMenu() {
  const menu = document.getElementById('toolsMenu');
  const button = document.getElementById('toolsMenuButton');
  if (menu) menu.hidden = true;
  if (button) button.setAttribute('aria-expanded', 'false');
}
function toggleToolsMenu() {
  const menu = document.getElementById('toolsMenu');
  menu.hidden = !menu.hidden;
  document.getElementById('toolsMenuButton').setAttribute('aria-expanded', String(!menu.hidden));
}
function runUiFileTest() {
  document.body.classList.remove('mobile-sidebar-open');
  testFileWrite();
}
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 180) + 'px';
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    closeToolsMenu();
    document.body.classList.remove('mobile-sidebar-open');
  }
});
document.addEventListener('click', event => {
  const menu = document.getElementById('toolsMenu');
  const button = document.getElementById('toolsMenuButton');
  if (menu && button && !menu.contains(event.target) && !button.contains(event.target)) {
    closeToolsMenu();
  }
});

