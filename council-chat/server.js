// Council Chat — local web server.
// Serves the chat UI and, on each question, runs every enabled model's CLI in
// parallel, then has the synthesizer merge their answers into one reply.
import express from 'express';
import { marked } from 'marked';
import path from 'node:path';
import { promises as fs } from 'node:fs';
import { fileURLToPath } from 'node:url';
import * as store from './lib/store.js';
import { runModel } from './lib/runModel.js';
import { synthesize } from './lib/synthesize.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 4717;

marked.setOptions({ gfm: true, breaks: true });

function renderMarkdown(md) {
  if (!md) return '';
  return marked
    .parse(md)
    // Light sanitize — answers come from your own models, but be safe anyway.
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son\w+\s*=\s*'[^']*'/gi, '');
}

const CONFIG_PATH = path.join(__dirname, 'council.config.json');

async function readRawConfig() {
  return JSON.parse(await fs.readFile(CONFIG_PATH, 'utf8'));
}

async function writeConfig(cfg) {
  await fs.writeFile(CONFIG_PATH, JSON.stringify(cfg, null, 2));
}

async function loadConfig() {
  const cfg = await readRawConfig();
  if (process.env.COUNCIL_MOCK === '1') cfg.mock = true;
  return cfg;
}

const app = express();
app.use(express.json({ limit: '2mb' }));
app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/config', async (_req, res) => {
  const cfg = await loadConfig();
  res.json({
    mock: !!cfg.mock,
    synthesizerId: cfg.synthesizerId,
    models: cfg.models.filter((m) => m.enabled).map((m) => ({ id: m.id, label: m.label, color: m.color }))
  });
});

// Settings panel: read the editable config, and save changes back to the file.
app.get('/api/settings', async (_req, res) => {
  const cfg = await loadConfig();
  res.json({
    synthesizerId: cfg.synthesizerId,
    effortOptions: cfg.effortOptions || ['', 'minimal', 'low', 'medium', 'high'],
    mock: !!cfg.mock,
    models: cfg.models.map((m) => ({
      id: m.id,
      label: m.label,
      color: m.color,
      enabled: !!m.enabled,
      model: m.model || '',
      effort: m.effort || '',
      supportsEffort: Array.isArray(m.effortArgs) && m.effortArgs.length > 0
    }))
  });
});

app.post('/api/settings', async (req, res) => {
  const body = req.body || {};
  const cfg = await readRawConfig(); // raw, so we never persist a mock override
  if (typeof body.synthesizerId === 'string') cfg.synthesizerId = body.synthesizerId;
  if (Array.isArray(body.models)) {
    const updates = Object.fromEntries(body.models.map((m) => [m.id, m]));
    for (const m of cfg.models) {
      const u = updates[m.id];
      if (!u) continue;
      if (typeof u.enabled === 'boolean') m.enabled = u.enabled;
      if (typeof u.model === 'string') m.model = u.model.trim();
      if (typeof u.effort === 'string') m.effort = u.effort;
    }
  }
  await writeConfig(cfg);
  res.json({ ok: true });
});

app.get('/api/sessions', async (_req, res) => {
  res.json(await store.listSessions());
});

app.post('/api/sessions', async (_req, res) => {
  res.json(await store.createSession());
});

function renderAssistant(msg) {
  return {
    ...msg,
    synthesis: msg.synthesis ? { ...msg.synthesis, html: renderMarkdown(msg.synthesis.content) } : null,
    panel: (msg.panel || []).map((p) => ({ ...p, html: p.ok ? renderMarkdown(p.content) : '' }))
  };
}

app.get('/api/sessions/:id', async (req, res) => {
  const s = await store.getSession(req.params.id);
  if (!s) return res.status(404).json({ error: 'Session not found' });
  res.json({ ...s, messages: s.messages.map((m) => (m.role === 'assistant' ? renderAssistant(m) : m)) });
});

app.delete('/api/sessions/:id', async (req, res) => {
  await store.deleteSession(req.params.id);
  res.json({ ok: true });
});

app.post('/api/sessions/:id/ask', async (req, res) => {
  const question = (req.body && req.body.question ? String(req.body.question) : '').trim();
  if (!question) return res.status(400).json({ error: 'Empty question' });

  const cfg = await loadConfig();
  const opts = { timeoutMs: cfg.timeoutMs || 180000, mock: !!cfg.mock };
  const enabled = cfg.models.filter((m) => m.enabled);
  if (enabled.length === 0) return res.status(400).json({ error: 'No models enabled in council.config.json' });

  await store.addMessage(req.params.id, { role: 'user', content: question, ts: Date.now() });

  const panelPrompt = `${cfg.panelInstruction}\n\nQuestion:\n${question}`;

  // Fan out to every model at once. One model failing never blocks the others.
  const panel = await Promise.all(
    enabled.map(async (m) => {
      const r = await runModel(m, panelPrompt, opts);
      return { id: m.id, label: m.label, color: m.color, ok: r.ok, content: r.content, error: r.error, ms: r.ms };
    })
  );

  const synthModel = cfg.models.find((m) => m.id === cfg.synthesizerId) || enabled[0];
  const synth = await synthesize(synthModel, question, panel, opts);

  const assistantMsg = {
    role: 'assistant',
    ts: Date.now(),
    synthesis: {
      content: synth.ok ? synth.content : `⚠️ Synthesis failed: ${synth.error || 'unknown error'}`,
      by: synth.by,
      byId: synth.byId,
      ok: synth.ok,
      ms: synth.ms
    },
    panel
  };

  await store.addMessage(req.params.id, assistantMsg);
  res.json(renderAssistant(assistantMsg));
});

app.listen(PORT, () => {
  console.log(`\n  ⛬  Council Chat is running\n      Open  →  http://localhost:${PORT}\n`);
});
