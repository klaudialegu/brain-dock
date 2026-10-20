---
name: wrap-up
description: End-of-session routine. Use when Klaudia types /wrap-up or says she's done, stopping, or out of time.
---
1. Run the tests and report pass/fail in one line.
2. Summarize what changed in max 3 bullets.
3. Log any new concepts from this session to docs/LEARNING_LOG.md (use the /learn format) that aren't there yet.
4. Tick finished boxes in ROADMAP.md.
5. Rewrite NEXT.md: Last session (date + what got done), Next step (one concrete action small enough to start in 5 minutes), Open questions.
6. Privacy check: scan `git diff --staged` for secrets, tokens, emails, phone numbers, real names of recruiters/contacts, resumes, .db files. Report "privacy check: clean" or list what to remove. Never commit until clean.
7. If Claude made a mistake this session, propose a one-line CLAUDE.md rule so it doesn't happen again, and add it after Klaudia approves.
8. Propose a commit message. Commit only after Klaudia says OK.
