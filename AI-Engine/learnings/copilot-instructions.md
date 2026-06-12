# Copilot Repository Instructions

## Backend-Driven Architecture (Mandatory Primary Rule)

**This is the foundational principle — all other rules derive from this.**

- **Backend is authoritative.** All business logic, data validation, authorization checks, and state management live in the backend (`backend/app/`).
- **Frontend is dumb (presentation-only).** The client (`web`, `iOS`, `Android`) ONLY handles:
  - UI rendering & user interaction
  - Form input collection & submission
  - Response display & error messaging
  - No business logic, no validation logic, no authorization decisions
- **Zero internal exposure.** User NEVER sees:
  - Internal schema, database structure, or field names (use clean DTOs)
  - API keys, secrets, or environment variables
  - Backend error stack traces or implementation details
  - SQL queries, database IDs, or system metadata
  - Authentication tokens or session details in console/logs
- **Secrets live only in GCP Secret Manager.** All secrets must be stored, accessed, and rotated through Google Cloud Secret Manager. Do not store secrets in frontend code, repo files, local env files committed to git, or alternative secret stores.
- **Authentication is primary.** Every API call MUST be authenticated. Every mutation (POST/PUT/DELETE) MUST be authorized. Frontend sends auth headers; backend validates and enforces.
- **API contracts are strict.** Frontend and backend agree on:
  - Request schemas (what client sends)
  - Response schemas (what backend returns)
  - Error formats & status codes
  - No surprises, no undocumented fields, no schema drift
- **Canonical domains are fixed.** Frontend UI base URL remains `core.tuskus.com`. Frontend base API remains `api.tuskus.com`. Do not introduce alternate production base URLs unless the user explicitly requests an infrastructure migration.

### Access Control Priority (Non-Negotiable)

- **Access control is business-critical for this application.** Treat authorization correctness as a release blocker, not a polish task.
- **Deny by default.** Any module/action/scope not explicitly granted by backend permissions must remain inaccessible.
- **No frontend-only trust.** Frontend visibility checks are convenience UX only; backend must always enforce final authorization on every read/write path.
- **No scope drift.** Role, delegation, module aliases, and permission scopes must stay consistent between bootstrap payloads, middleware checks, and route guards.
- **No silent privilege expansion.** Any fallback logic must never grant broader access than an explicit permission assignment.
- **Approval actions are high-risk operations.** Approval/rejection workflows must always validate actor authority against the request owner at execution time.
- **Security over convenience.** If there is any conflict between UX convenience and strict authorization, strict authorization wins.

### Access Control Gate (Required Before PR)

1. ✅ Every protected route has backend authorization checks
2. ✅ No module/action executes without explicit permission validation
3. ✅ Delegation paths are validated server-side and time-bounded
4. ✅ Bootstrap/profile permission payloads are canonical and normalized
5. ✅ Notification-driven approvals still enforce full backend authorization
6. ✅ No fallback path can escalate permissions beyond assigned scope

### Enforcement Checklist

Before any PR submission:

1. ✅ **ZERO business logic in frontend code** — grep the frontend for business rules; find none
2. ✅ **All mutations go through backend APIs** — no direct cache writes, no local state mutations without backend sync
3. ✅ **Backend validates all inputs** — length, type, format, authorization, rate limits, duplicates
4. ✅ **Error messages are user-friendly** — no internal details leaked in UI error text
5. ✅ **Auth tokens never exposed** — not in localStorage unencrypted, not logged, not sent as query params
6. ✅ **API endpoints are RESTful & documented** — clear request/response contracts in PR description or API docs
7. ✅ **Database never accessed from client** — no client-side SQL, no direct Firestore reads without security rules enforced server-side
8. ✅ **Environment variables are server-only** — `EXPO_PUBLIC_*` only for non-sensitive values (URLs, feature flags); secrets stay in backend
9. ✅ **Secrets come only from GCP Secret Manager** — no duplicate secret storage in source, local config, or alternate vaults
10. ✅ **Canonical production domains preserved** — frontend UI stays on `core.tuskus.com`; frontend API stays on `api.tuskus.com`

---

## Cross-Platform Development (Mandatory)

All development **MUST** be done for all three platforms simultaneously:

- **Web** (React Native Web via Expo)
- **Android** (React Native via Expo)
- **iOS** (React Native via Expo)

Do NOT develop for a single platform and defer cross-platform work. Every feature, bug fix, refactor, or config change must be tested and working on all three platforms before submission.

### Cross-Platform Checklist

Before marking any task complete:

1. ✅ Code changes implemented for shared modules (`src/`, `components/`, `hooks/`, `services/`)
2. ✅ Platform-specific files created when needed (`.web.tsx`, `.ios.tsx`, `.android.tsx`, `.native.tsx`)
3. ✅ Tested on **Web** — UI, navigation, API calls, forms, permissions working
4. ✅ Tested on **Android** — layout, touch targets, native modules, permissions working
5. ✅ Tested on **iOS** — layout, safe areas, native modules, permissions working
6. ✅ No platform-specific errors or warnings in console logs
7. ✅ No errors/warnings in TypeScript (`npm run type-check`)
8. ✅ No linting issues (`npm run lint`)
9. ✅ No SonarQube issues (see below)

---

## Module Awareness (Mandatory)

When we talk about modules, we mean business domains such as execution, store, human resource, accounts, quantity, survey, and similar company departments.

- Each module is an independent department with its own responsibilities, workflows, and data ownership boundaries.
- Modules are also interconnected. Their relevant connections, dependencies, and data flow must be understood before changing anything inside a module.
- When redesigning a module or working inside a module, first understand the module in the context of the full product, its upstream/downstream dependencies, and how it interacts with other modules.
- Do not treat a module as an isolated screen or folder; treat it as part of a larger company workflow with shared business rules and data links.
- Preserve existing connections unless a change explicitly requires reworking them, and update all affected module integrations together.

---

## Error & SonarQube Resolution (Mandatory & Parallel)

This is a hard limit: while developing, do not proceed with feature work while known type/lint/SonarQube/platform errors are pending. Resolve issues in parallel as they appear.

All errors, problems, and SonarQube issues **MUST be resolved in parallel** across:

- **Type checking errors** — from `npm run type-check`
- **Linting errors** — from `npm run lint`
- **SonarQube code quality issues** — from `mcp_snyk_snyk_code_scan`
- **Platform-specific console errors** — from web, Android, and iOS

### Error Resolution Workflow

1. **Run checks in parallel** for all platforms simultaneously (web, Android, iOS console)
2. **Identify ALL issues** across type-checking, linting, and SonarQube before fixing
3. **Fix errors holistically** — don't fix one platform and leave another broken
4. **Resolve SonarQube issues** as part of the PR, not as technical debt
5. **Re-run all checks** after each fix to ensure no regressions

### SonarQube Code Scanning

Before any PR submission:

```bash
# Run SonarQube scan on modified files
snyk code scan <path-to-modified-files>

# Acceptable resolution:
# - Fix all HIGH and CRITICAL severity issues
# - Document and justify any MEDIUM/LOW issues not fixed (in PR description)
# - Zero unaddressed issues on first submission
```

Do NOT merge PRs with unresolved SonarQube HIGH/CRITICAL issues. If issues exist, fix them and re-run the scan.

---

## Workspace Cleanliness & Maintainability (Hard Limit)

During development, keep the workspace clean at all times.

- Build reusable shared components first. Prefer one well-designed component reused in multiple places over duplicate implementations.
- Prefer minimal lines of code with high clarity: eliminate repetition, centralize common logic, and avoid boilerplate.
- Use shared assets (icons, images, tokens, constants, styles) from common folders; do not duplicate assets per screen.
- No unused imports, variables, functions, types, constants, files, routes, pages, or components.
- No abandoned scaffolding, commented-out dead code, or duplicate legacy implementations left behind.
- When replacing a feature/page/component, remove the old implementation and references in the same task.
- Prefer small, cohesive modules with clear naming and single responsibility.
- Keep shared code DRY and avoid copy-paste divergence across screens/platform variants.

### Cleanliness Checklist

1. ✅ Remove dead code and stale references in the same PR
2. ✅ Ensure no orphaned page/component/route remains after refactors
3. ✅ Ensure lint and type checks catch unused code (`npm run lint`, `npm run type-check`)
4. ✅ Keep code readable and maintainable: clear names, minimal complexity, no hidden side effects
5. ✅ Update tests/docs when behavior or structure changes
6. ✅ Reuse shared components/hooks/utils before creating new ones
7. ✅ Keep assets centralized and reused from shared asset folders

---

## UI Space Efficiency & Layout Discipline (Mandatory)

- Do not stretch panels, cards, chips, or tiles just to fill available space when the content does not require that footprint.
- Every UI block must justify its occupied area with information density, hierarchy, or interaction value.
- Prefer compact grouped summaries over repeating related metrics in separate oversized cards.
- When two stats belong to one entity, group them under the entity title first, then present only the needed breakdown. Example: `Tenants` with `Active` and `Total`, not separate large cards for each tenant stat.
- Do not duplicate the same information in multiple neighboring blocks unless one is a summary and the other is a deeper drill-down.
- Expanded/disclosure views must use content-driven layouts. Use asymmetric or span-based grids where needed; avoid equal-width columns that create empty space.
- Actions should live in the overview/header area when possible, not in isolated oversized cards with little content.
- Before shipping a UI, check for wasted screen real estate, over-padded empty surfaces, stretched components, and repeated metrics. Tighten the layout before considering the screen done.

---

## Expo Server Runtime (Mandatory)

When asked to start Expo, always start the interactive dev server that shows QR and full runtime logs.

- Use `npx expo start` (or `npx expo start --go` if user asks specifically for Expo Go).
- Run Expo in a visible VS Code integrated terminal panel so the developer can see QR/options/logs directly.
- Keep terminal output visible so QR, device options, and logs stay accessible.
- Do NOT run Expo Go in hidden/internal terminals or background-only sessions that are not visible to the developer.
- Do NOT daemonize Expo (`nohup`, detached background with logs redirected away from terminal) unless the user explicitly asks.
- Keep the Expo session running until the user explicitly asks to stop it.
- Do not treat long-running Expo output as a blocker; continue assisting while the dev server remains active.

### Expo Session Rules

1. ✅ Start Expo in interactive mode with QR and menu options visible
2. ✅ Preserve live logs in terminal for debugging
3. ✅ Maintain the running session unless explicitly stopped by user request
4. ✅ If restart is required, restart immediately and restore interactive output
5. ✅ Keep Expo running in a developer-visible VS Code terminal, not hidden/internal execution channels

---

## Canonical Deployment Path (Mandatory)

When asked to deploy this project, use exactly one command path:

- Production deploy: `npm run deploy:one`
- Staging deploy: `npm run deploy:staging`

Do not use ad-hoc deployment commands such as direct `wrangler deploy`, `gcloud run deploy`, manual Docker deployment, or any alternative flow unless the user explicitly asks to bypass the canonical path.

## Deployment Definition

The canonical deployment command is responsible for:

1. Type checks (`npm run type-check`)
2. Lint (`npm run lint`)
3. Web export build (`npm run export:web`)
4. Frontend deploy through Wrangler (`npx wrangler deploy --config wrangler.toml`)
5. Backend deploy by dispatching `.github/workflows/deploy-backend.yml` and waiting for completion

If deployment fails, fix the root cause and retry using the same canonical command.
