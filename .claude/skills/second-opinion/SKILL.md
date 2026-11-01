---
name: second-opinion
description: Independent review by the reviewer subagent before a plan approval, a merge, or anything hard to undo. Use when Klaudia types /second-opinion [target], and whenever the Review rules in CLAUDE.md call for it.
---
1. Work out the target: the argument if given, otherwise the current plan or branch diff.
2. Call the reviewer subagent (.claude/agents/reviewer.md) with ONLY the target (file paths, branch, PR number) and the slice goal. Never pass along your own reasoning or summary.
3. Act on the verdict using the Review rules in CLAUDE.md.
4. Show Klaudia a short card: verdict emoji + one line, what you fixed automatically (max 3 one-liners), and any decision she needs to make as A/B with your recommendation first. Never paste the full review table unless she asks.
