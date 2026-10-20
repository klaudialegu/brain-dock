---
name: explain-diff
description: Friendly code review of pending changes before a commit. Use when Klaudia types /explain-diff, asks "what changed" or "walk me through this", and before proposing any commit.
---
1. Get the changes: `git diff --staged`. If nothing is staged, use `git diff` and say so. Also list untracked files from `git status --short`.
2. Start with a one-line summary: what this change does for Brain Dock, in plain words.
3. Walk through it file by file, in the order that makes the story clearest (data model → logic → routes → templates → tests), not alphabetically. For each file:
   - What changed (2-3 sentences, no line-by-line narration)
   - Why it changed (the problem it solves or the decision behind it)
   - One thing worth noticing: a pattern, a trade-off, or a concept she's new to (frontend, web frameworks, CI/CD, agent design)
4. Review like a kind senior colleague. Flag, briefly:
   - Logic without a pytest test
   - Anything that looks wrong, risky, or more complex than it needs to be
   - Privacy concerns (secrets, personal data, logging of email bodies or tokens)
   - A decision worth an ADR (suggest /adr)
   If nothing to flag, say "Nothing to flag."
5. New concepts that came up: offer to log them with /learn. Don't log without asking.
6. End with one question Klaudia should be able to answer about this change. It's a self-check, not a quiz she's graded on.
7. Do not commit. Explaining and committing are separate steps.
