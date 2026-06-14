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

async function loadConfig() {
  const cfg = JSON.parse(await fs.readFile(path.join(__dirname, 'council.config.json'), 'utf8'));
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
