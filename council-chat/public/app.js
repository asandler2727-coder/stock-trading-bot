// Council Chat — front-end logic. Plain JS, no framework, no build step.
const state = { config: null, sessions: [], currentId: null, sending: false };
const el = (id) => document.getElementById(id);
const messagesEl = () => el('messages');

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || res.statusText);
  }
  return res.json();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );
}

const emptyStateHtml = () =>
  `<div class="empty-state"><div class="empty-mark">⛬</div><h1>Ask the council</h1>` +
  `<p>Your question goes to every model at once. They answer in parallel, then one synthesizes the single best reply.</p></div>`;

async function loadConfig() {
  state.config = await api('/api/config');
  el('panelBadges').innerHTML = state.config.models
    .map((m) => `<span class="badge" style="--c:${m.color}">${escapeHtml(m.label)}</span>`)
    .join('');
  const mode = el('modeBadge');
  if (state.config.mock) {
    mode.textContent = '● Mock mode — showing sample answers. Configure your CLIs to go live.';
    mode.style.display = 'block';
  }
}

async function loadSessions() {
  state.sessions = await api('/api/sessions');
  renderSessionList();
}

function renderSessionList() {
  const list = el('sessionList');
  list.innerHTML = '';
  for (const s of state.sessions) {
    const item = document.createElement('div');
    item.className = 'session-item' + (s.id === state.currentId ? ' active' : '');
    item.innerHTML =
      `<span class="session-name">${escapeHtml(s.title || 'New chat')}</span>` +
      `<button class="session-del" title="Delete chat">×</button>`;
    item.querySelector('.session-name').onclick = () => openSession(s.id);
    item.querySelector('.session-del').onclick = async (e) => {
      e.stopPropagation();
      await api('/api/sessions/' + s.id, { method: 'DELETE' });
      if (state.currentId === s.id) {
        state.currentId = null;
        messagesEl().innerHTML = emptyStateHtml();
        el('sessionTitle').textContent = 'New chat';
      }
      await loadSessions();
    };
    list.appendChild(item);
  }
}

async function newChat() {
  const s = await api('/api/sessions', { method: 'POST' });
  state.currentId = s.id;
  await loadSessions();
  messagesEl().innerHTML = emptyStateHtml();
  el('sessionTitle').textContent = s.title;
  el('input').focus();
}

async function openSession(id) {
  state.currentId = id;
  const s = await api('/api/sessions/' + id);
  el('sessionTitle').textContent = s.title || 'New chat';
  renderSessionList();
  const m = messagesEl();
  m.innerHTML = '';
  if (!s.messages.length) m.innerHTML = emptyStateHtml();
  for (const msg of s.messages) appendMessage(msg);
  scrollBottom();
}

function scrollBottom() {
  const m = messagesEl();
  m.scrollTop = m.scrollHeight;
}

function appendUser(text) {
  const m = messagesEl();
  const empty = m.querySelector('.empty-state');
  if (empty) empty.remove();
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  m.appendChild(div);
  scrollBottom();
}

function appendMessage(msg) {
  if (msg.role === 'user') return appendUser(msg.content);
  const m = messagesEl();
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.appendChild(renderAssistant(msg));
  m.appendChild(div);
  scrollBottom();
}

function renderAssistant(msg) {
  const wrap = document.createElement('div');
  wrap.className = 'assistant-card';
  const by = msg.synthesis && msg.synthesis.by ? `· Synthesized by ${escapeHtml(msg.synthesis.by)}` : '';
  const panel = msg.panel || [];
  const okCount = panel.filter((p) => p.ok).length;

  const panelCards = panel
    .map(
      (p) => `
      <div class="panel-card ${p.ok ? '' : 'err'}" style="--c:${p.color || '#888'}">
        <div class="panel-head"><span class="panel-dot"></span>${escapeHtml(p.label)}
          <span class="panel-ms">${p.ms ? (Math.round(p.ms / 100) / 10) + 's' : ''}</span></div>
        <div class="panel-body markdown">${
          p.ok ? (p.html || '') : `<span class="panel-error">${escapeHtml(p.error || 'No answer')}</span>`
        }</div>
      </div>`
    )
    .join('');

  wrap.innerHTML = `
    <div class="synthesis">
      <div class="synthesis-head"><span class="syn-dot"></span> Council answer <span class="syn-by">${by}</span></div>
      <div class="syn-body markdown">${msg.synthesis ? msg.synthesis.html || escapeHtml(msg.synthesis.content || '') : ''}</div>
    </div>
    <details class="panel-details">
      <summary>Council details — ${okCount}/${panel.length} models answered</summary>
      <div class="panel-grid">${panelCards}</div>
    </details>`;
  return wrap;
}

function deliberatingNode() {
  const div = document.createElement('div');
  div.className = 'msg assistant';
  const chips = state.config.models
    .map((m) => `<span class="think-chip" style="--c:${m.color}"><span class="think-dot"></span>${escapeHtml(m.label)}</span>`)
    .join('');
  div.innerHTML = `<div class="assistant-card deliberating"><div class="delib-head">The council is deliberating…</div><div class="think-chips">${chips}</div></div>`;
  return div;
}

async function send() {
  if (state.sending) return;
  const input = el('input');
  const text = input.value.trim();
  if (!text) return;
  if (!state.currentId) await newChat();

  state.sending = true;
  el('send').disabled = true;
  input.value = '';
  autosize();
  appendUser(text);
  const delib = deliberatingNode();
  messagesEl().appendChild(delib);
  scrollBottom();

  try {
    const msg = await api('/api/sessions/' + state.currentId + '/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: text })
    });
    delib.remove();
    appendMessage(msg);
    await loadSessions();
    const cur = state.sessions.find((s) => s.id === state.currentId);
    if (cur) el('sessionTitle').textContent = cur.title;
  } catch (e) {
    delib.remove();
    const errDiv = document.createElement('div');
    errDiv.className = 'msg assistant';
    errDiv.innerHTML = `<div class="assistant-card"><div class="synthesis"><div class="syn-body markdown">⚠️ ${escapeHtml(e.message)}</div></div></div>`;
    messagesEl().appendChild(errDiv);
    scrollBottom();
  } finally {
    state.sending = false;
    el('send').disabled = false;
    input.focus();
  }
}

function autosize() {
  const t = el('input');
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 220) + 'px';
}

function init() {
  el('newChat').onclick = newChat;
  el('send').onclick = send;
  const input = el('input');
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  loadConfig();
  loadSessions();
}

document.addEventListener('DOMContentLoaded', init);
