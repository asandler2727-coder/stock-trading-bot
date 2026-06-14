// Runs a single model's CLI once and captures its answer.
// Each model is spawned as a child process with its prompt passed as an argument
// (no shell, so nothing in your question can be misinterpreted as a command).
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { promises as fs } from 'node:fs';
import crypto from 'node:crypto';

// Used only in mock mode so the app can be demoed without the real CLIs.
const MOCK_ANSWERS = {
  claude:
    "**Short version: yes, with one caveat.**\n\nFrom Claude's seat on the council, here's the reasoning:\n\n1. The core recommendation holds in most cases.\n2. Watch the edge case where assumptions break down.\n\n_(mock answer — real Claude Code will respond here once configured)_",
  chatgpt:
    "I largely agree. One thing worth flagging: the second-order effect most people miss.\n\n- Consideration A\n- Consideration B\n\n_(mock answer — real Codex CLI will respond here once configured)_",
  gemini:
    "A slightly different angle: in one specific scenario the data points the other way, so don't over-generalize.\n\n_(mock answer — real Gemini CLI will respond here once configured)_",
  grok:
    "Blunt take: the practical answer is X. The debate around Y is mostly noise.\n\n_(mock answer — real Grok CLI will respond here once configured)_"
};

function mockFor(id) {
  return MOCK_ANSWERS[id] || `Mock answer from ${id}.`;
}

function fillTemplate(command, prompt) {
  return command.map((part) => part.split('{{PROMPT}}').join(prompt));
}

export async function runModel(model, prompt, { timeoutMs = 180000, mock = false } = {}) {
  const start = Date.now();

  if (mock) {
    await new Promise((r) => setTimeout(r, 600 + Math.random() * 1600));
    return { ok: true, content: mockFor(model.id), error: null, ms: Date.now() - start };
  }

  // Run in a throwaway temp dir so agentic CLIs never touch your real files.
  const cwd = path.join(os.tmpdir(), `council-${model.id}-${crypto.randomUUID()}`);
  await fs.mkdir(cwd, { recursive: true });
  const cleanup = () => fs.rm(cwd, { recursive: true, force: true }).catch(() => {});

  const [cmd, ...args] = fillTemplate(model.command, prompt);

  return new Promise((resolve) => {
    let stdout = '';
    let stderr = '';
    let settled = false;

    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      cleanup();
      resolve({ ...result, ms: Date.now() - start });
    };

    let child;
    try {
      child = spawn(cmd, args, { cwd, env: process.env });
    } catch (err) {
      return finish({ ok: false, content: '', error: `Could not launch "${cmd}": ${err.message}` });
    }

    // Close stdin so a CLI never sits waiting for interactive input.
    try { child.stdin.end(); } catch { /* ignore */ }

    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch { /* ignore */ }
      finish({ ok: false, content: stdout.trim(), error: `Timed out after ${Math.round(timeoutMs / 1000)}s` });
    }, timeoutMs);

    child.stdout.on('data', (d) => { stdout += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });

    child.on('error', (err) => {
      const hint =
        err.code === 'ENOENT'
          ? `Command "${cmd}" not found. Install that CLI, or fix its "command" in council.config.json.`
          : err.message;
      finish({ ok: false, content: '', error: hint });
    });

    child.on('close', (code) => {
      const text = stdout.trim();
      if (text) {
        // Got output — use it even on a non-zero exit (CLIs sometimes warn on stderr).
        finish({ ok: true, content: text, error: null });
      } else {
        finish({ ok: false, content: '', error: (stderr.trim() || `Exited with code ${code} and gave no output`).slice(0, 600) });
      }
    });
  });
}
