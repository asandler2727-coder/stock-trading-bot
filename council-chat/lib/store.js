// Tiny JSON-file session store. One file per chat under ./data/sessions/.
// No database, no native deps — just files, so it always installs cleanly.
import { promises as fs } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, '..', 'data', 'sessions');

async function ensureDir() {
  await fs.mkdir(DATA_DIR, { recursive: true });
}

function sessionPath(id) {
  return path.join(DATA_DIR, `${id}.json`);
}

export async function listSessions() {
  await ensureDir();
  const files = await fs.readdir(DATA_DIR);
  const sessions = [];
  for (const f of files) {
    if (!f.endsWith('.json')) continue;
    try {
      const s = JSON.parse(await fs.readFile(path.join(DATA_DIR, f), 'utf8'));
      sessions.push({ id: s.id, title: s.title, createdAt: s.createdAt, updatedAt: s.updatedAt });
    } catch {
      /* skip unreadable files */
    }
  }
  sessions.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  return sessions;
}

export async function getSession(id) {
  await ensureDir();
  try {
    return JSON.parse(await fs.readFile(sessionPath(id), 'utf8'));
  } catch {
    return null;
  }
}

async function saveSession(s) {
  await ensureDir();
  s.updatedAt = Date.now();
  await fs.writeFile(sessionPath(s.id), JSON.stringify(s, null, 2));
  return s;
}

export async function createSession(title = 'New chat') {
  const now = Date.now();
  const s = { id: crypto.randomUUID(), title, createdAt: now, updatedAt: now, messages: [] };
  return saveSession(s);
}

export async function addMessage(id, message) {
  const s = await getSession(id);
  if (!s) return null;
  s.messages.push(message);
  // Auto-title the chat from the first thing you asked.
  if ((!s.title || s.title === 'New chat') && message.role === 'user') {
    s.title = message.content.replace(/\s+/g, ' ').trim().slice(0, 60) || 'New chat';
  }
  return saveSession(s);
}

export async function deleteSession(id) {
  try {
    await fs.unlink(sessionPath(id));
    return true;
  } catch {
    return false;
  }
}
