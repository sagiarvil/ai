
function getOrCreateSessionId() {
  let sid = localStorage.getItem('barisChatSessionId');
  if (!sid) {
    sid = crypto.randomUUID();
    localStorage.setItem('barisChatSessionId', sid);
  }
  return sid;
}

async function streamChatResponse(text, box) {
  const sessionId = getOrCreateSessionId();
  box.innerHTML = '<span class="loading-cursor">▋</span>';
  let fullText = '';
  
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      message: text,
      session_id: sessionId
    })
  });

  if (!response.ok) {
    throw new Error('Streaming sunucu yanıtı başarısız: ' + response.statusText);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    const lines = buffer.split('
');
    buffer = lines.pop();

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || !trimmed.startsWith('data:')) continue;
      const dataStr = trimmed.slice(5).trim();
      if (dataStr === '[DONE]') {
        break;
      }
      try {
        const parsed = JSON.parse(dataStr);
        if (parsed.token) {
          fullText += parsed.token;
          box.innerHTML = '';
          renderMarkdownContent(box, fullText);
          const cursor = document.createElement('span');
          cursor.className = 'loading-cursor';
          cursor.textContent = '▋';
          box.appendChild(cursor);
          feed.scrollTop = feed.scrollHeight;
        }
      } catch (e) {}
    }
  }

  box.innerHTML = '';
  renderMarkdownContent(box, fullText || 'Yanıt tamamlandı.');
  feed.scrollTop = feed.scrollHeight;
}


function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatInlineMarkdown(text) {
  let s = escapeHtml(text);
  s = s.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/`([^`]+)`/g, '<code class="pro-inline-code">$1</code>');
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" class="pro-link">$1</a>');
  return s;
}

function renderMarkdownContent(container, text) {
  if (!text) {
    const p = document.createElement("p");
    p.textContent = "İşlem açıklaması yok.";
    container.appendChild(p);
    return;
  }

  const rootDiv = document.createElement("div");
  rootDiv.className = "pro-report-card";

  const lines = text.split(/\r?\n/);
  let i = 0;

  while (i < lines.length) {
    let line = lines[i];
    let trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    // Fenced Code Block
    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim();
      i++;
      let codeLines = [];
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;

      const codeBox = document.createElement("div");
      codeBox.className = "pro-code-box";

      const codeBar = document.createElement("div");
      codeBar.className = "pro-code-bar";

      const langSpan = document.createElement("span");
      langSpan.className = "pro-code-lang";
      langSpan.textContent = lang || "terminal";

      const copyBtn = document.createElement("button");
      copyBtn.className = "pro-copy-btn";
      copyBtn.type = "button";
      copyBtn.textContent = "Kopyala";
      const codePayload = codeLines.join("\n");
      copyBtn.onclick = function() {
        navigator.clipboard.writeText(codePayload);
        copyBtn.textContent = "Kopyalandı!";
        setTimeout(function() { copyBtn.textContent = "Kopyala"; }, 2000);
      };

      codeBar.appendChild(langSpan);
      codeBar.appendChild(copyBtn);

      const pre = document.createElement("pre");
      const codeElem = document.createElement("code");
      codeElem.textContent = codePayload;
      pre.appendChild(codeElem);

      codeBox.appendChild(codeBar);
      codeBox.appendChild(pre);
      rootDiv.appendChild(codeBox);
      continue;
    }

    // Başlıklar
    if (trimmed.startsWith("#### ")) {
      const h4 = document.createElement("h4");
      h4.className = "pro-h4";
      h4.innerHTML = formatInlineMarkdown(trimmed.replace(/^####\s+/, ""));
      rootDiv.appendChild(h4);
      i++;
      continue;
    }
    if (trimmed.startsWith("### ")) {
      const h3 = document.createElement("h3");
      h3.className = "pro-h3";
      h3.innerHTML = formatInlineMarkdown(trimmed.replace(/^###\s+/, ""));
      rootDiv.appendChild(h3);
      i++;
      continue;
    }
    if (trimmed.startsWith("## ")) {
      const h2 = document.createElement("h2");
      h2.className = "pro-h2";
      h2.innerHTML = formatInlineMarkdown(trimmed.replace(/^##\s+/, ""));
      rootDiv.appendChild(h2);
      i++;
      continue;
    }
    if (trimmed.startsWith("# ")) {
      const h1 = document.createElement("h1");
      h1.className = "pro-h1";
      h1.innerHTML = formatInlineMarkdown(trimmed.replace(/^#\s+/, ""));
      rootDiv.appendChild(h1);
      i++;
      continue;
    }

    // Tablo
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      let tableRows = [];
      while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
        const cells = lines[i].trim().slice(1, -1).split("|").map(c => c.trim());
        tableRows.push(cells);
        i++;
      }

      if (tableRows.length > 0) {
        const wrap = document.createElement("div");
        wrap.className = "pro-table-wrap";
        const table = document.createElement("table");
        table.className = "pro-table";

        let isHeader = true;
        let alignments = [];

        for (const r of tableRows) {
          if (r.every(c => /^[\s:-]+$/.test(c))) {
            alignments = r.map(c => {
              const trm = c.trim();
              if (trm.startsWith(":") && trm.endsWith(":")) return "center";
              if (trm.endsWith(":")) return "right";
              return "left";
            });
            isHeader = false;
            continue;
          }

          const tr = document.createElement("tr");
          r.forEach((cellText, idx) => {
            const cell = document.createElement(isHeader ? "th" : "td");
            cell.innerHTML = formatInlineMarkdown(cellText);
            let align = alignments[idx] || "left";
            if (!isHeader && /^[\s\d.,]+(kg|TL|adet|kWh|%|\$|€)?\s*$/i.test(cellText)) {
              align = "right";
            }
            if (align === "right") cell.className = "num-cell";
            else if (align === "center") cell.className = "center-cell";
            tr.appendChild(cell);
          });
          table.appendChild(tr);
          isHeader = false;
        }
        wrap.appendChild(table);
        rootDiv.appendChild(wrap);
      }
      continue;
    }

    // Listeler
    const isUnordered = /^[-*•]\s+/.test(trimmed);
    const isOrdered = /^\d+\.\s+/.test(trimmed);

    if (isUnordered || isOrdered) {
      const listTag = isOrdered ? "ol" : "ul";
      const listElem = document.createElement(listTag);
      listElem.className = "pro-list " + (isOrdered ? "pro-list-ol" : "pro-list-ul");

      while (i < lines.length) {
        const lTrim = lines[i].trim();
        if (!lTrim) break;
        if (isOrdered && /^\d+\.\s+/.test(lTrim)) {
          const li = document.createElement("li");
          li.innerHTML = formatInlineMarkdown(lTrim.replace(/^\d+\.\s+/, ""));
          listElem.appendChild(li);
          i++;
        } else if (!isOrdered && /^[-*•]\s+/.test(lTrim)) {
          const li = document.createElement("li");
          li.innerHTML = formatInlineMarkdown(lTrim.replace(/^[-*•]\s+/, ""));
          listElem.appendChild(li);
          i++;
        } else {
          break;
        }
      }
      rootDiv.appendChild(listElem);
      continue;
    }

    // Paragraf
    let paraLines = [];
    while (i < lines.length) {
      const lTrim = lines[i].trim();
      if (!lTrim) break;
      if (lTrim.startsWith("```") || lTrim.startsWith("#") || (lTrim.startsWith("|") && lTrim.endsWith("|")) || /^[-*•]\s+/.test(lTrim) || /^\d+\.\s+/.test(lTrim)) {
        break;
      }
      paraLines.push(lines[i]);
      i++;
    }

    if (paraLines.length > 0) {
      const p = document.createElement("p");
      p.className = "pro-body-p";
      p.innerHTML = formatInlineMarkdown(paraLines.join("<br>"));
      rootDiv.appendChild(p);
    }
  }

  container.appendChild(rootDiv);
}

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
      info.build !== 'local-ui-v10' || info.tool_loop !== true) {
    throw new Error('Arayüz ve motor sürümü uyuşmuyor.');
  }
  return info;
}

async function refreshConnection() {
  try {
    const info = await engineInfo();
    if (info.scheduler_alive === false) throw new Error('Görev zamanlayıcısı durmuş; yeni görev gönderimi kapalı.');
    if (info.queue_blocked === true) throw new Error('Belirsiz dış komut kaydı var; kuyruk inceleme bekliyor.');
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
  if (data.engine_protocol !== 'baris-execution-v2' || !['local-ui-v5', 'local-ui-v6', 'local-ui-v7', 'local-ui-v8', 'local-ui-v9', 'local-ui-v10'].includes(data.build)) {
    throw new Error('Yanıt beklenen motora ait değil.');
  }
  const steps = Array.isArray(data.execution_steps) ? data.execution_steps : [];
  const verified = data.status === 'VERIFIED' && data.verified === true &&
    steps.length > 0 && data.acceptance && data.acceptance.success === true;
  box.replaceChildren();
  const heading = document.createElement('strong');
  heading.textContent = verified ? (data.verification_scope === 'exact_files' ? 'DOSYA KABULÜ DOĞRULANDI' : 'GÖREV DOĞRULANDI') :
    data.status === 'FAILED' ? 'GÖREV BAŞARISIZ' :
    data.status === 'CANCELLED' ? 'GÖREV İPTAL EDİLDİ' :
    data.status === 'BLOCKED' ? 'İNCELEME GEREKİYOR' :
    (steps.length ? 'İŞLEM VAR; SONUÇ DOĞRULANMADI' : 'İŞLEM TAMAMLANMADI');
  box.appendChild(heading);
  renderMarkdownContent(box, data.reply);
  if (data.verification_scope === 'exact_files') {
    const scope = document.createElement('p');
    scope.textContent = 'Doğrulama kapsamı: belirtilen dosyaların birebir içeriği.';
    box.appendChild(scope);
  }
  if (Number.isFinite(data.budget_seconds)) {
    const timing = document.createElement('p');
    timing.textContent = 'Kullanılan süre: ' + Math.ceil(data.used_seconds || 0) +
      ' / ' + data.budget_seconds + ' sn' + (data.failure_code ? ' • Kod: ' + data.failure_code : '');
    box.appendChild(timing);
  }
  // Araç isimleri (tool_write_file, tool_run_shell vb.) ana sonuç ekranından kaldırıldı.
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
    const isExplicitDurableTask = expectedFiles || /\b(dosya|kod\s+yaz|kaydet|gitleaks|test\s+et)\b/i.test(text);
    if (!isExplicitDurableTask) {
      clearInterval(timer);
      await streamChatResponse(text, box);
    } else {
      const payload = {message: text};
      if (expectedFiles) payload.expected_files = expectedFiles;
      const submitted = await submitPayload(payload);
      localStorage.setItem('barisActiveTask', submitted.task_id);
      localStorage.removeItem('barisPendingSubmission');
      clearInterval(timer);
      await followTask(submitted.task_id, box);
    }

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
function activityState(job, now = Date.now()/1000) {
  const event = job.latest_event || (job.events || []).at(-1);
  const age = Math.max(0, Math.floor(now - (event?.at || job.created || now)));
  if (terminalStates.has(job.status)) return {mode: 'finished', label: 'Görev sonlandı', age};
  if (job.status === 'QUEUED') return {mode: 'queued', label: 'Sırada bekliyor', age};
  if (age >= 90) return {mode: 'waiting', label: 'Uzun bekleme · Yeni ilerleme yok; durduğu doğrulanmadı', age};
  if (age >= 15) return {mode: 'waiting', label: 'Sunucu bağlı · Yeni ilerleme bekleniyor', age};
  const kind = event?.kind;
  const label = kind === 'MODEL_PROGRESS' ? 'Model üretiyor' :
    kind === 'TOOL_START' ? 'Araç çalışıyor' :
    kind === 'MODEL_START' ? 'Model yanıtı bekleniyor' :
    kind === 'MODEL_RETRY' ? 'Kontrollü yeniden deneme' : 'Görev işleniyor';
  return {mode: 'active', label, age};
}

async function followTask(taskId, box) {
  activeTaskId = taskId;
  let lastSeq = 0;
  let lastMessage = 'Görev sırada bekliyor.';
  let networkErrors = 0;
  const activity = document.createElement('div');
  activity.setAttribute('role', 'status');
  activity.setAttribute('aria-live', 'polite');
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
      if (job.latest_event?.data?.message) {
        lastMessage = job.latest_event.data.message;
        if (job.latest_event.kind === 'MODEL_PROGRESS') lastMessage += ' • ' + job.latest_event.data.characters + ' karakter';
      }
      const state = activityState(job);
      activity.className = 'task-activity is-' + state.mode;
      activity.textContent = state.label + ' • Son kayıt ' + state.age + ' sn önce';
      box.replaceChildren(activity);
      const message = document.createElement('p');
      message.textContent = lastMessage;
      const identity = document.createElement('p');
      identity.textContent = taskTiming(job, taskId);
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
      activity.className = 'task-activity is-offline';
      activity.textContent = 'Bağlantı kesildi · Çalışma durumu doğrulanamıyor';
      const offline = document.createElement('p');
      offline.textContent = 'Görev tekrar gönderilmiyor. Görev: ' + taskId;
      box.replaceChildren(activity, offline);
      if (networkErrors >= 15) throw new Error('Bağlantı kesildi. Görev kaydı korundu; sayfayı yenileyerek izlemeye devam et.');
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}
function taskTiming(job, taskId) {
  const elapsed = Math.floor((Date.now()/1000) - job.created);
  return 'Görev: ' + taskId + ' • Geçen ' + elapsed + ' sn' +
    (Number.isFinite(job.budget_seconds) ? ' • Çalışma bütçesi ' + Math.ceil(job.used || 0) +
      '/' + job.budget_seconds + ' sn • Kalan ' + Math.ceil(job.remaining_seconds || 0) + ' sn' : '');
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

input.addEventListener('input', () => {
  if (connected && !busy && input.value.trim().length > 0) {
    sendBtn.disabled = false;
  }
});

input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendAction();
  }
});

// Anında bağlantı kontrolü ve 3 saniyede bir periyodik durum heartbeat
refreshConnection();
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', refreshConnection);
}
window.addEventListener('load', refreshConnection);
setInterval(refreshConnection, 3000);


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
