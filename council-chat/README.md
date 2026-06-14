# Council Chat

A local chat window that asks **all your AI subscriptions at once** — Claude, ChatGPT,
Gemini, and Grok — then has one of them synthesize a single best answer. It's the
"council" / OpenRouter-Fusion idea, but running on the CLIs you log into with your
**existing subscriptions**, so there's no per-token API bill.

- 🪟 Looks like a normal chat app — sidebar of past chats, saved history, clean styling
- ⚡ Every model answers **in parallel**; one model then **merges** them into one reply
- 🔎 Expand **"Council details"** to see exactly what each model said
- 🧱 One model failing or timing out never breaks the others
- 💸 Runs on your **subscriptions** via each vendor's official CLI — no API keys

---

## Quick start

```bash
cd council-chat
npm install
npm start
```

Then open **http://localhost:4717**. On a Mac you can also just **double-click `start.command`**.

> **Want to see it before installing the CLIs?** Run `npm run mock` — it fills the
> council with sample answers so you can try the interface immediately.

---

## One-time setup: install & log into the four CLIs

You only do this once per CLI. Each one opens a browser so you can sign in with your
**subscription** (not an API key). After that, this app calls them silently.

| Model | Install | Sign in | Subscription |
|-------|---------|---------|--------------|
| **Claude** | `npm install -g @anthropic-ai/claude-code` | run `claude`, then `/login` | Claude Pro/Max |
| **ChatGPT** | `npm install -g @openai/codex` | `codex login` → "Sign in with ChatGPT" | ChatGPT Plus/Pro |
| **Gemini** | `npm install -g @google/gemini-cli` | run `gemini`, sign in with Google | Google account (free tier works) |
| **Grok** | `curl -fsSL https://x.ai/cli/install.sh \| bash` | run `grok`, sign in (OAuth) | SuperGrok / X Premium+ |

To confirm a CLI works on its own, try its one-shot mode, e.g.:

```bash
claude -p "say hello in one word"
gemini -p "say hello in one word"
codex exec --skip-git-repo-check "say hello in one word"
grok -p "say hello in one word"
```

> CLI flags occasionally change between versions. If a model errors in the app, that's
> almost always the fix → see **Customizing** below. The exact command each model runs
> lives in `council.config.json`.

---

## Customizing — `council.config.json`

Everything is controlled by this one file. No code needed.

- **Turn a model on/off** → set `"enabled": true|false`
- **Choose who merges the answers** → `"synthesizerId"` (default `"claude"`)
- **Fix or pin a model's command** → edit its `"command"`. `{{PROMPT}}` is replaced with
  your question. To pin a specific model, add its flag, e.g.
  `["claude", "--model", "claude-opus-4-8", "-p", "{{PROMPT}}"]`
  or `["codex", "exec", "--skip-git-repo-check", "-m", "gpt-5.5", "{{PROMPT}}"]`.
- **Timeout** → `"timeoutMs"` (default 180000 = 3 min per model)

After editing, just refresh the page — changes are picked up on the next question.

---

## Troubleshooting

- **A model card shows a red error like `Command "grok" not found`** → that CLI isn't
  installed or isn't on your PATH. Install it, or fix its `command` in the config.
- **`Exited with code 1 / no output` or an auth message** → the CLI's login expired.
  Run the CLI once in your terminal and sign in again.
- **It's slow** → that's expected. You're running 4 models plus a synthesis pass; 15–40s
  per question is normal. The council trades speed for quality.
- **Nothing loads at localhost:4717** → make sure `npm start` is still running in the
  terminal; that window is the app's engine.

---

## How it works

```
your question
   │
   ├─► claude  -p  …  ┐
   ├─► codex  exec …  │  all run in parallel
   ├─► gemini -p   …  │  (each in a throwaway temp dir)
   └─► grok   -p   …  ┘
                      │
            collect every answer
                      │
        synthesizer model merges them
                      │
        one "Council answer" + expandable details
```

Chats are stored as plain JSON files under `data/sessions/` on your machine. Nothing
leaves your computer except the calls each CLI makes to its own vendor.

---

## Prior art / credits

The subscription-CLI panel approach is validated by other projects in this space — notably
[`calvinnwq/swarm`](https://github.com/calvinnwq/swarm), a CLI batch tool that also drives
`claude`/`codex` logins and runs multi-round panels with deterministic report synthesis.
This project differs by being a **chat app** (sessions, history, UI) with **LLM-based**
synthesis and Gemini + Grok in the panel. Worth a look if you later want structured,
multi-round *decision reports* instead of a conversational answer.
