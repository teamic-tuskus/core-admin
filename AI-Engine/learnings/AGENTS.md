# Agent Rules For This Repository

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

- **Access control is critical infrastructure for this product.** Authorization mistakes are treated as blocking defects.
- **Default deny posture.** If a module/action/scope is not explicitly granted by backend permissions, access must be denied.
- **Backend is final authority.** Frontend checks can hide/show UI, but only backend authorization determines what can be read, created, approved, updated, or deleted.
- **Permission consistency is mandatory.** Module aliases, scope semantics, role assignments, and delegation behavior must match across bootstrap responses, middleware, and route enforcement.
- **No implicit privilege expansion.** Fallbacks must preserve least privilege and never broaden access beyond explicit grants.
- **Approval workflows are security-sensitive.** Every approve/reject action must revalidate actor authority against the target owner at execution time.
- **Security wins over convenience.** If UX shortcuts conflict with strict access control, enforce strict access control.

### Access Control Gate (Required Before PR)

1. ✅ Backend route authorization exists for all protected endpoints
2. ✅ Sensitive actions have explicit permission checks (module/action/scope)
3. ✅ Delegation and proxy approvals are validated server-side with active windows
4. ✅ Effective permissions are canonicalized before frontend consumption
5. ✅ Notification-based actions still execute through backend authorization
6. ✅ No fallback logic can escalate privilege scope

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

Never develop for a single platform and defer cross-platform work. Every feature, bug fix, refactor, or config change must be tested and working on all three platforms before submission.

### Cross-Platform Requirements

Before marking any task complete, verify:

1. ✅ Shared code in `src/`, `components/`, `hooks/`, `services/`
2. ✅ Platform-specific variants created when needed (`.web.tsx`, `.ios.tsx`, `.android.tsx`, `.native.tsx`)
3. ✅ **Web tested** — full UI, navigation, API, forms, permissions
4. ✅ **Android tested** — layout, touch targets, native modules, permissions
5. ✅ **iOS tested** — layout, safe areas, native modules, permissions
6. ✅ **No console errors** on any platform
7. ✅ **TypeScript passes** — `npm run type-check`
8. ✅ **Linting passes** — `npm run lint`
9. ✅ **SonarQube clean** — no unresolved HIGH/CRITICAL issues

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

**All errors and SonarQube issues MUST be resolved in parallel:**

- Type checking errors (`npm run type-check`)
- Linting errors (`npm run lint`)
- SonarQube issues (`snyk code scan`)
- Console errors (web, Android, iOS)

### Resolution Workflow

1. **Identify ALL issues** across all platforms and all tools before fixing
2. **Fix issues holistically** — don't leave any platform broken
3. **Resolve SonarQube HIGH/CRITICAL** before PR submission
4. **Re-run all checks** after fixes to ensure no regressions
5. **Zero unaddressed issues** on first PR submission

Do NOT defer SonarQube, linting, or type errors to follow-up PRs or technical debt. Fix them as part of the current task.

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

## Deployment (Mandatory Single Path)

When a user asks to deploy, always use this exact command path:

- Production: `npm run deploy` (alias of `npm run deploy:one`)
- Staging: `npm run deploy:staging`

Do not deploy via any other direct command (`wrangler deploy`, `gcloud run deploy`, manual Docker, or ad-hoc scripts) unless the user explicitly requests bypassing this policy.

## Canonical Deploy Flow

`npm run deploy` runs `scripts/deploy.sh` which performs:

1. `npm run type-check`
2. `npm run lint`
3. `npm run export:web`
4. `npx wrangler deploy --config wrangler.toml`
5. Dispatch + watch `.github/workflows/deploy-backend.yml`

If deployment fails, fix the issue and retry with the same canonical command.
