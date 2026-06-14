// Council Chat — front-end logic. Plain JS, no framework, no build step.
const state = { config: null, sessions: [], currentId: null, sending: false, drawer: null };
const panels = {}; // pid -> panel array, so the drawer can navigate between models
let panelSeq = 0;
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
  closeDrawer();
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

  const pid = 'p' + ++panelSeq;
  panels[pid] = panel;

  const rows = panel
    .map(
      (p, i) => `
      <div class="panel-row ${p.ok ? '' : 'err'}" data-pid="${pid}" data-idx="${i}">
        <span class="panel-dot" style="--c:${p.color || '#888'}"></span>
        <span class="panel-row-name">${escapeHtml(p.label)}</span>
        <span class="panel-row-status">${p.ok ? 'Answered' : 'Error'}</span>
        <span class="panel-row-ms">${p.ms ? (Math.round(p.ms / 100) / 10) + 's' : ''}</span>
        <span class="panel-row-chev">›</span>
      </div>`
    )
    .join('');

  wrap.innerHTML = `
    <div class="synthesis">
      <div class="synthesis-head"><span class="syn-dot"></span> Council answer <span class="syn-by">${by}</span></div>
      <div class="syn-body markdown">${msg.synthesis ? msg.synthesis.html || escapeHtml(msg.synthesis.content || '') : ''}</div>
    </div>
    <div class="panel-list">
      <div class="panel-label-row">Council · ${okCount}/${panel.length} answered — click a model to read its full response</div>
      ${rows}
    </div>`;

  wrap.querySelectorAll('.panel-row').forEach((row) => {
    row.onclick = () => openDrawer(row.dataset.pid, Number(row.dataset.idx));
  });
  return wrap;
}

function renderDrawer() {
  const d = state.drawer;
  const panel = d && panels[d.pid];
  if (!panel) return closeDrawer();
  const p = panel[d.idx];
  el('drawerTitle').textContent = p.label;
  el('drawerDot').style.background = p.color || '#888';
  el('drawerCount').textContent = `${d.idx + 1}/${panel.length}`;
  el('drawerMs').textContent = p.ms ? (Math.round(p.ms / 100) / 10) + 's' : '';
  el('drawerBody').innerHTML = p.ok
    ? (p.html || '<em>No content.</em>')
    : `<div class="panel-error">${escapeHtml(p.error || 'No answer')}</div>`;
  el('drawerBody').scrollTop = 0;
  el('drawer').classList.add('open');
  el('drawer').setAttribute('aria-hidden', 'false');
  el('drawerScrim').classList.add('open');
}

function openDrawer(pid, idx) {
  state.drawer = { pid, idx };
  renderDrawer();
}

function closeDrawer() {
  state.drawer = null;
  el('drawer').classList.remove('open');
  el('drawer').setAttribute('aria-hidden', 'true');
  el('drawerScrim').classList.remove('open');
}

function drawerStep(delta) {
  if (!state.drawer) return;
  const panel = panels[state.drawer.pid];
  if (!panel) return;
  let i = state.drawer.idx + delta;
  if (i < 0) i = panel.length - 1;
  if (i >= panel.length) i = 0;
  state.drawer.idx = i;
  renderDrawer();
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
  el('drawerClose').onclick = closeDrawer;
  el('drawerScrim').onclick = closeDrawer;
  el('drawerPrev').onclick = () => drawerStep(-1);
  el('drawerNext').onclick = () => drawerStep(1);

  const input = el('input');
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (!state.drawer) return;
    if (e.key === 'Escape') closeDrawer();
    else if (e.key === 'ArrowLeft') drawerStep(-1);
    else if (e.key === 'ArrowRight') drawerStep(1);
  });

  loadConfig();
  loadSessions();
}

document.addEventListener('DOMContentLoaded', init);
