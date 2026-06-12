---
name: expert-developer-focus
description: 'Expert implementation workflow for page/function/action tasks. Use for feature work, bug fixes, refactors, and reviews when you must do detailed pre-change analysis from user input, web research, and codebase context; apply best practices; identify and fix gaps in priority; keep modules small and interconnected with fail strategy; stay strictly in scope; and enforce strict password/secret handling.'
argument-hint: 'Task scope (page/function/action), expected outcome, and constraints'
---

# Expert Developer Focus Workflow

Use this skill when implementing or fixing a specific page, function, or action and you want execution to be context-aware, scoped, resilient, and clean.

## Outcomes

- Understand relevant system context before editing.
- Perform deep analysis from user request, web research, and existing code before changes.
- Use available subagents to improve structure quality, consistency checks, and clean enterprise-grade outcomes.
- Apply best practices and identify gaps before finalizing.
- Keep modules small, cohesive, and interconnected.
- Add fail strategy so the system continues to function under failure/load conditions.
- Work only inside the requested scope.
- Remove stale leftovers and resolve discovered issues with priority.
- Ensure passwords/secrets are never stored in exposed files and are migrated to secure storage immediately when found.

## When To Use

Trigger phrases and intents:

- "implement this page"
- "fix this function"
- "update this action"
- "refactor module"
- "review and fix"
- "clean up leftovers"
- "handle failure strategy"
- "out of scope"

## Procedure

1. Define strict scope.
2. Perform mandatory detailed analysis.
3. Run focused web research.
4. Analyze developed codebase details.
5. Find best-practice gaps.
6. Implement smallest safe change.
7. Add fail strategy for resilience.
8. Handle password/secret exposure immediately.
9. Clean leftovers and dead code.
10. Validate and resolve issues by priority.
11. Report changes and residual risk.

## Step Details

### 1) Define Strict Scope

- Parse the request into one of: page, function, or action.
- Declare explicit in-scope items and out-of-scope items.
- Do not modify unrelated modules, routes, or infra unless blocked by the requested task.

Decision point:

- If required dependency changes expand scope, ask for approval before proceeding.

### 2) Perform Mandatory Detailed Analysis

- Parse and restate the user request in precise engineering terms.
- Extract all explicit requirements, constraints, and completion criteria from user input.
- Identify missing details or ambiguities that can change implementation decisions.
- Confirm the context: what is being changed, why it is being changed, and expected outcome.

Completion check:

- You can clearly state requested task, boundaries, constraints, and acceptance criteria before editing.

### 3) Run Focused Web Research

- Research current official guidance relevant to the task before coding.
- Prefer authoritative sources: framework docs, platform docs, security references, and vendor best practices.
- Capture only findings that affect implementation decisions; avoid noisy or outdated patterns.

Decision point:

- If web guidance conflicts with repository architecture, preserve repository constraints and document the tradeoff.

### 3.1) Orchestrate Subagents For Structured Delivery

- Use available subagents for read-only exploration and validation before editing when task complexity is medium/high.
- Use subagent findings to tighten scope, detect architecture gaps, and avoid ad-hoc changes.
- Integrate subagent output into a clean implementation plan with clear file boundaries.

Completion check:

- Subagent-driven findings are reflected in the implementation plan and risk list.

### 4) Analyze Developed Codebase Details

- Read only the files needed for the task path.
- Map upstream/downstream dependencies touching the requested page/function/action.
- Understand current behavior, contracts, and failure points.
- Review existing implementation details deeply enough to avoid duplicate logic and regressions.

Completion check:

- You can explain current behavior and affected paths in 3-5 lines.

### 5) Find Best-Practice Gaps

- Check for missing validation, error handling, retries/timeouts, or authorization boundaries.
- Check for oversized modules and coupling; split into smaller composable units where needed.
- Check naming clarity, duplication, and hidden side effects.

Decision point:

- If a gap is critical for correctness/security/stability, stop and ask approval before fixing if it is out of scope.
- If a gap is non-critical and out of scope, log it as a follow-up note.

### 6) Implement Smallest Safe Change

- Prefer minimal edits over broad rewrites.
- Keep public contracts stable unless the request explicitly changes them.
- Preserve existing architecture patterns and coding style.

### 7) Add Fail Strategy For Resilience

- Add explicit fallback behavior for recoverable failures.
- Use bounded retries/timeouts/circuit-break style behavior where applicable.
- Ensure graceful degradation and user-safe error messages.
- Avoid single points of failure between interconnected modules.

Completion checks:

- Failure of one dependency does not crash the full flow.
- Failure path is observable and returns controlled output.

### 8) Handle Password/Secret Exposure Immediately

- Never store passwords, credentials, or secrets in source files, logs, fixtures, comments, or docs.
- If any password/secret is found during edits, treat it as an immediate security issue.
- Remove exposed secret material from edited files in the same task.
- Migrate secret values to approved secure secret storage.
- In CoreAdmin, use GCP Secret Manager as the required secure destination.
- Replace hardcoded secrets with references to secure retrieval at runtime.
- Avoid echoing secret values in terminal output or responses.

Decision point:

- If secure migration requires operational access not available in-session, remove exposure, add secure placeholder/reference, and report exact follow-up required.

### 9) Clean Leftovers And Dead Code

- Remove replaced implementations, stale imports, dead branches, and unused symbols.
- Remove orphaned references created by the change.
- Keep the codebase cleaner than before the task.

### 10) Validate And Resolve Issues By Priority

Priority order:

1. Correctness and security defects
2. Runtime failures and regressions
3. Type/lint/test errors introduced by the change
4. Maintainability and cleanup issues

Required checks (run what is available in the target repo):

- Type checks
- Lint
- Targeted tests or smoke verification

Decision point:

- If checks fail due to your change, fix before completion.
- If unrelated pre-existing failures block completion, report clearly and isolate your impact.

### 11) Report Changes And Residual Risk

- Summarize what changed, why, and how scope was respected.
- List resolved gaps and any deferred non-critical items.
- State residual risks and recommended next step.

## Quality Gate (Must Pass)

- Scope was respected with no out-of-scope edits.
- Detailed analysis was completed from user input, web research, and codebase context.
- Subagent findings were used for structured planning when complexity required it.
- Module boundaries are small and coherent.
- Failure strategy exists for key risk points.
- No exposed password/secret remains in touched paths.
- No stale/legacy leftovers remain from touched paths.
- Checks for changed code paths are green or clearly explained if pre-existing.

## Enterprise Delivery Standard

- Design and implementation must remain production-ready, maintainable, and auditable.
- Prefer layered architecture and clear separation of concerns.
- Keep modules small, cohesive, and replaceable.
- Enforce naming consistency, explicit contracts, and deterministic error handling.
- Prioritize cleanliness: no partial rewrites, no dangling code, no hidden side effects.
