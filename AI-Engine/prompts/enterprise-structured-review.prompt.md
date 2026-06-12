---
description: "Enterprise structured implementation review. Use when you need deep pre-change analysis, web-backed best practices, subagent-assisted context checks, strict scope control, and production-ready cleanup guidance."
name: "Enterprise Structured Review"
argument-hint: "Task, scope (page/function/action), and constraints"
agent: "Super Structured Enterprise"
---
Perform an enterprise-grade structured review for the provided task.

Required workflow:
1. Restate user intent, explicit scope, and out-of-scope boundaries.
2. Extract acceptance criteria and unknowns from user input.
3. Run focused web guidance checks using authoritative sources only.
4. Run subagent-assisted codebase exploration for affected paths and dependencies.
5. Produce a concise risk map: correctness, security, resilience, maintainability.
6. Produce a minimal safe implementation plan with module boundaries.
7. Include password/secret exposure checks and secure migration actions.
8. End with a production-readiness checklist and validation commands.

Output format:
- Task understanding
- Scope and constraints
- Web research findings
- Codebase findings
- Gaps and risks
- Implementation plan
- Secret safety actions
- Validation checklist

Do not propose out-of-scope code edits unless explicitly marked and approved.