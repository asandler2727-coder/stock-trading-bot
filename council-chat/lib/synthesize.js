// Takes every panel member's answer and asks the synthesizer model to merge
// them into one best reply — the "fusion" step.
import { runModel } from './runModel.js';

export function buildSynthesisPrompt(question, panel) {
  const answered = panel.filter((p) => p.ok && p.content && p.content.trim());

  let prompt = `You are the synthesizer for an advisory council of AI assistants. The user asked the question below, and each assistant gave its own answer. Produce the single best possible answer for the user.

Guidelines:
- Merge the strongest reasoning from across the answers.
- Resolve contradictions; when you must choose, pick the better-supported position.
- Silently correct clear mistakes.
- If the assistants disagree on something genuinely important, note that disagreement briefly so the user knows it is contested.
- Do not narrate this process, and do not thank or name the panel unless a disagreement makes it useful. Just give the user a clean, well-structured answer in markdown.

# User's question
${question}

# Panel answers
`;

  if (answered.length === 0) {
    prompt += '\n(No panel member returned a usable answer. Answer the question yourself as best you can.)\n';
  } else {
    for (const p of answered) {
      prompt += `\n## ${p.label}\n${p.content}\n`;
    }
  }

  return prompt;
}

export async function synthesize(synthModel, question, panel, opts) {
  const prompt = buildSynthesisPrompt(question, panel);
  const res = await runModel(synthModel, prompt, opts);

  if (opts.mock) {
    const names = panel.filter((p) => p.ok).map((p) => p.label).join(', ');
    res.content =
      `Here is the council's merged answer.\n\n` +
      `Drawing on ${names || 'the panel'}, the consensus is **yes, with caveats**. The strongest points:\n\n` +
      `1. The recommendation the whole panel agreed on.\n` +
      `2. A caveat one member raised that is worth keeping in mind.\n` +
      `3. The blunt practical takeaway.\n\n` +
      `> The panel disagreed slightly on edge cases, but the merged recommendation above holds.\n\n` +
      `_(Mock synthesis. With your CLIs configured, ${synthModel.label} writes the real one.)_`;
    res.ok = true;
  }

  return { by: synthModel.label, byId: synthModel.id, ...res };
}
