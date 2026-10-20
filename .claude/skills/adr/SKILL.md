---
name: adr
description: Write a short Architecture Decision Record into docs/decisions/. Use when Klaudia types /adr <decision>, or when a real decision was made (stack, library, data model change, outside service).
---
1. If the decision, the options, or the reason isn't clear from the conversation, ask in one short message. Don't invent reasons.
2. Number it: find the highest NNNN in docs/decisions/ and add 1 (start at 0001). File name: docs/decisions/NNNN-short-kebab-title.md.
3. Write it in this format, under one page:

# NNNN. <Title>
**Status:** Accepted | Proposed | Superseded by NNNN
**Date:** <YYYY-MM-DD>

## Context
What problem or constraint forced a choice. 2-4 sentences.

## Decision
What we chose, in one or two sentences.

## Options considered
- <Option>: why not (one line each)

## Consequences
- Good: ...
- Trade-off: ...

4. ADRs are public. No personal data: no recruiter names, companies Klaudia applied to, salaries, or emails. Use generic wording.
5. If this replaces an older ADR, set the old one's status to "Superseded by NNNN".
6. Show the file and suggest a `docs:` commit message. Commit only after Klaudia says OK.
