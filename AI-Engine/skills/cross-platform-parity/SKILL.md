---
name: cross-platform-parity
description: 'Enforce cross-platform parity across web, iOS, and Android, require whole-project holistic context, and enforce backend-driven architecture. USE FOR: every feature, bug fix, refactor, dependency bump, config change, styling tweak, navigation change, API contract change, or env/secret change in this repo. The agent MUST consult this skill before editing code, opening PRs, adding screens/components/routes, wiring APIs, changing build configs (app.json, eas.json, metro.config, next.config, tsconfig), or shipping a release. Triggers: "add feature", "implement", "build screen", "fix bug", "refactor", "ship", "release", "platform", "ios", "android", "web", "expo", "react native", "responsive", "native module", "permission", "deep link", "push notification", "auth", "navigation", "backend", "api", "business logic".'
---

# Cross-Platform Parity & Holistic Project Awareness

This is the **Recon** project: a single application that ships to **Web + iOS + Android**.
Recommended stack (chosen for single-codebase simplicity, best DX, and broad community support):
**Expo SDK + React Native + Expo Router + TypeScript** (web target via React Native Web).

Every change MUST satisfy three non-negotiable rules:

1. **Backend-First Rule** — all business logic, validation, authorization, and state live in the backend. Frontend is dumb (display-only).
2. **Parity Rule** — no change is "done" until it works correctly on web, iOS, and Android.
3. **Holistic Rule** — never edit with narrow sight. Survey the full project (routes, backend APIs, shared modules, native config, CI, tests, docs) before and after the change.

---

## Backend-Driven Architecture (Foundation)

This rule supersedes all others. Violations compromise security, maintainability, and testability.

- **Backend is the source of truth.** All business logic, data validation, authorization checks, and state management MUST live in `backend/app/`.
- **Frontend is presentation-only.** The client (`web`, `iOS`, `Android`) ONLY handles:
  - UI rendering & user interaction
  - Form input collection & submission to backend APIs
  - Response display & error messaging
  - ❌ NO business logic, NO validation logic, NO authorization decisions
- **Zero internal exposure to users:**
  - ❌ No internal schema, database structure, or field names (use clean DTOs)
  - ❌ No API keys, secrets, or environment variables
  - ❌ No backend error stack traces or implementation details
  - ❌ No SQL queries, database IDs, or system metadata
  - ❌ No authentication tokens or session details in logs/console
- **Secrets live only in GCP Secret Manager:**
  - All secrets must be stored, accessed, and rotated through Google Cloud Secret Manager
  - ❌ Never store secrets in frontend code, repo files, committed env files, or alternate secret stores
- **Canonical production domains are fixed:**
  - Frontend UI base URL is `core.tuskus.com`
  - Frontend base API URL is `api.tuskus.com`
  - ❌ Do not introduce alternate production domains unless the user explicitly requests an approved infrastructure migration
- **Authentication & Authorization are primary:**
  - Every API call MUST be authenticated
  - Every mutation (POST/PUT/DELETE) MUST be authorized by the backend
  - Frontend sends auth headers; backend validates and enforces
- **API contracts are strict:**
  - Frontend and backend agree on request schemas (what client sends)
  - Frontend and backend agree on response schemas (what backend returns)
  - Error formats, status codes, and edge cases documented
  - No surprises, no undocumented fields, no schema drift

### Checklist Before Any PR

1. ✅ **ZERO business logic in frontend** — grep for any business rules; find none
2. ✅ **All mutations through backend APIs** — no local state mutations without backend sync
3. ✅ **Backend validates all inputs** — length, type, format, authorization, rate limits, duplicates
4. ✅ **User-friendly errors only** — no internal details leaked in UI error text
5. ✅ **Auth tokens never exposed** — not in localStorage, not logged, not in query params, not in console
6. ✅ **API endpoints clear & documented** — request/response contracts visible in PR or API docs
7. ✅ **Database never accessed from client** — no client-side SQL, no direct Firestore reads without server-side rules
8. ✅ **Environment variables server-only** — `EXPO_PUBLIC_*` only for non-sensitive values; secrets in backend
9. ✅ **Secrets sourced only from GCP Secret Manager** — no duplicate storage in source, local config, or alternate vaults
10. ✅ **Canonical production domains preserved** — UI stays on `core.tuskus.com`; API stays on `api.tuskus.com`

---

## Module Awareness (Mandatory)

When this repo refers to a module, it means a business domain such as execution, store, human resource, accounts, quantity, survey, and similar company departments.

- A module is an independent department with its own responsibilities, workflows, and data ownership boundaries.
- Modules are interconnected, so their relevant connections, dependencies, and data flow must be understood before changing anything inside a module.
- Before redesigning a module or working inside one, understand it in the context of the full product, its upstream/downstream dependencies, and how it interacts with other modules.
- Do not treat a module as an isolated screen or folder; treat it as part of a larger company workflow with shared business rules and data links.
- Preserve existing connections unless a change explicitly requires reworking them, and update all affected module integrations together.

---

## Quality Hard Limits (Parallel Resolution + Clean Workspace)

These are non-optional during development:

1. **Parallel error resolution hard limit** — do not continue feature implementation while known type/lint/SonarQube/platform errors are pending.
2. **Clean workspace hard limit** — no unused, leftover, abandoned, or orphaned code/pages/components/routes/files.
3. **Reuse hard limit** — always prefer shared reusable components/hooks/utils and shared assets over per-screen duplication.
4. **Expo session hard limit** — when Expo is requested, run in interactive mode (QR + full logs) and keep the session alive until explicitly stopped.
5. **Latest-code hygiene hard limit** — always sync to the latest branch state and remove stale/generated artifacts before any validation or deployment.

Practical enforcement:

- Resolve type, lint, SonarQube, and platform runtime issues in parallel as they appear.
- Remove replaced or obsolete code in the same task; do not defer cleanup.
- Keep modules small, readable, and maintainable with clear boundaries and naming.
- Build once, reuse many: create composable components and consume them across routes/screens.
- Keep code minimal and DRY: avoid repeated JSX/styles/logic when a shared abstraction can be used.
- Keep assets centralized in shared locations and reuse them instead of cloning files.
- Keep Expo dev server interactive when requested: show QR + logs in terminal; do not hide output in detached background unless explicitly requested.
- Always run checks and deployments from the latest branch tip (`git fetch` + compare local/remote head).
- Remove stale/generated artifacts (for example `__pycache__/`, `*.pyc`, runtime logs, temporary files) before reporting status.
- Resolve leftover conflict or legacy residue before proceeding (merge markers, dead temporary files, obsolete duplicate paths).

---

## When to Use

Load this skill at the start of every coding task in this repo. If you are about to:

- create/modify a screen, component, hook, store, API client, or util
- add or upgrade a dependency
- change navigation, deep links, or auth flow
- touch styling, theming, fonts, icons, or assets
- request a device permission (camera, location, notifications, biometrics, files)
- change `app.json` / `app.config.ts`, `eas.json`, `metro.config.js`, `babel.config.js`, `next.config.*`, `tsconfig.json`, `package.json`, env files
- write or update tests, CI, or release scripts

…you MUST follow the procedure below.

---

## Procedure

### Step 1 — Holistic Survey (before editing)

Do these in parallel; do NOT skip even for "small" changes:

1. Read the repo root: `package.json`, `app.json` / `app.config.*`, `eas.json`, `tsconfig.json`, `metro.config.*`, `babel.config.*`, `next.config.*` (if present), `.env*.example`.
2. Map the source tree: `app/` (Expo Router routes), `src/` or `components/`, `hooks/`, `services/`, `stores/`, `theme/`, `assets/`, `__tests__/`, `e2e/`, `.github/workflows/`.
3. **Survey the entire backend system** — read `backend/` folder structure, `backend/app/main.py`, API routes, database schemas, middleware, and any service integrations. Understand the full API contract, database models, authentication flow, and how frontend changes affect backend endpoints.
4. **Map the entire system** — understand how frontend, backend, CI/CD, deployment, and external services (Firebase, databases, APIs) interconnect. Check `wrangler.toml`, `.github/workflows/`, and any infrastructure files.
5. Search for existing patterns related to your task (`grep` for similar component, hook, route, API endpoint, or backend logic). Reuse, don't duplicate.
6. Identify all consumers of any symbol you'll change (`vscode_listCodeUsages` or grep). Plan ripple updates across frontend AND backend.
7. If anything is unclear about platform impact or system dependencies, dispatch the **Explore** subagent with thoroughness=medium or thorough before writing code.

Output of Step 1: a short mental (or todo-list) plan listing every file you expect to touch on web, iOS, Android, shared, backend, tests, and docs — ensuring no changes are isolated to frontend alone without considering backend impact.

### Step 2 — Implement With Backend-First & Parity In Mind

Follow these patterns:

#### Backend Implementation

- **All business logic in backend** (`backend/app/`). Examples:
  - Data transformation & enrichment
  - Authorization logic & permission checks
  - Calculation & aggregation
  - Data validation (format, length, uniqueness, rate limits)
  - Database mutations & transactions
  - External service integrations (payment, auth, notifications)
- **Clean DTOs (Data Transfer Objects)** — expose only what the frontend needs; hide internal schema. Example:

  ```python
  # ❌ BAD: exposes internal DB structure
  @app.get("/users/{id}")
  def get_user(id):
      return db.User.get(id)  # returns all fields including internal IDs, passwords, etc.

  # ✅ GOOD: clean DTO
  @app.get("/users/{id}")
  def get_user(id):
      user = db.User.get(id)
      return UserDTO(name=user.name, email=user.email, role=user.role)  # only public fields
  ```

- **Every endpoint requires authentication/authorization** — no exceptions
  ```python
  @app.get("/data")
  @require_auth  # Decorator to enforce auth
  def get_data(current_user: User = Depends(get_current_user)):
      # Verify current_user has permission
      check_authorization(current_user, action="read_data")
      return data
  ```

#### Frontend Implementation

- **Collect & submit, don't validate.** Frontend collects form inputs and sends to backend:

  ```typescript
  // ❌ BAD: frontend validates
  const isValidEmail = /^[^@]+@[^@]+$/.test(email);
  if (!isValidEmail) setError("Invalid email");

  // ✅ GOOD: send to backend; let it validate & respond
  const result = await api.post("/auth/login", { email, password });
  if (result.error) setError(result.error); // user-friendly error from backend
  ```

- **Never store or expose auth tokens carelessly:**

  ```typescript
  // ❌ BAD
  localStorage.setItem("token", response.token); // unencrypted in localStorage
  console.log("Token:", token); // exposed in logs

  // ✅ GOOD: use secure storage
  await secureStore.setItem("token", response.token); // encrypted
  // Never log tokens; never pass in query params
  ```

- **Default to shared code.** Put logic in `src/` (or `components/`, `hooks/`, `services/`) so all three platforms get it for free.
- **Default to reusable components.** Prefer extending existing shared components before creating new screen-local components.
- **Platform-specific code** must use Expo's official mechanisms:
  - `Platform.OS === 'web' | 'ios' | 'android'` for small branches.
  - `File.web.tsx` / `File.ios.tsx` / `File.android.tsx` / `File.native.tsx` for divergent implementations. Always provide all required variants.
  - Wrap web-incompatible native modules behind a thin adapter that has a web fallback (never let the web bundle crash).
- **Styling must be responsive.** Mobile-first; verify tablet and desktop breakpoints on web. Prefer flexbox + `useWindowDimensions` over fixed pixel layouts. Respect safe-area insets on native.
- **Navigation:** use Expo Router so URLs/deep links work on web AND native. Every new route must have a working web URL and a native deep link.
- **Permissions, storage, notifications, auth, file pickers, camera, maps, biometrics:** use Expo modules (or libraries with documented web support). If a library is native-only, you MUST add a web fallback or feature-flag the UI on web.
- **Assets:** add icons/images via `expo-asset` or `require()`; verify they bundle for web (no Node-only paths).
- **Env & secrets:** use `expo-constants` / `EXPO_PUBLIC_*` vars only for non-sensitive values. All real secrets must be fetched from backend-managed GCP Secret Manager access. Preserve the production frontend domain as `core.tuskus.com` and the production API domain as `api.tuskus.com`.
- **Types:** strict TypeScript across the board. No `any` introduced by your change.

### Step 3 — Cross-Platform Verification (mandatory before declaring done)

Run all three. If a platform cannot be run locally, explicitly say so and run the rest.

If user asks to start Expo dev server during verification, keep it interactive and persistent:

- Start with `npx expo start` (or `npx expo start --go` for Expo Go specific ask)
- Keep QR/options/logs visible in terminal
- Keep session alive until user explicitly asks to stop
- Run Expo in a developer-visible VS Code integrated terminal, not a hidden/internal terminal
- Do not use detached background-only Expo sessions unless explicitly requested

```bash
# install (only when deps changed)
npm install            # or pnpm install / yarn

# Type + lint + unit
npx tsc --noEmit
npm run lint
npm test --if-present

# Web
npx expo start --web        # smoke-test the touched route(s)

# iOS (macOS only)
npx expo run:ios            # or: npx expo start --ios on a connected device/simulator

# Android
npx expo run:android        # or: npx expo start --android
```

For UI changes, capture or describe behavior on:

- **Web**: desktop (≥1280px), tablet (~768px), mobile (~375px) widths.
- **iOS**: at least one phone simulator (iPhone 15) and verify safe-area + dynamic type.
- **Android**: at least one phone emulator (Pixel) and verify back-button + status-bar.

### Step 4 — Holistic Wrap-Up

Before reporting "done":

- Re-grep for the symbol/route/feature name; confirm no dead references or stale docs.
- **Verify backend changes** — ensure all API endpoints, database models, and services are updated to support the frontend change. Run backend tests.
- **Check API contracts** — confirm frontend and backend agree on request/response schemas, authentication headers, and error handling.
- Update `README.md` and any `/docs` page that references the changed behavior (both frontend AND backend).
- Update tests (unit + integration/e2e on frontend AND backend if user-visible flow changed).
- Update CI workflow if new build/test steps are required (frontend AND backend).
- Update `app.json` / `eas.json` versioning if the change is shippable.
- Summarize in the PR description: **What changed, Why, Frontend/Backend/Web/iOS/Android verification status, System integration impact, Risks.**

---

## Hard Rules (do not violate)

### Backend-Driven Architecture (Non-Negotiable)

1. ❌ **NEVER put business logic in frontend.** No calculations, no aggregations, no authorization decisions. Backend does it all.
2. ❌ **NEVER validate on frontend as the source of truth.** Frontend can hint (UX); backend MUST validate.
3. ❌ **NEVER expose internal schema, database structure, or IDs to the user.** Use clean DTOs only.
4. ❌ **NEVER send secrets (API keys, tokens, passwords) to frontend.** All sensitive logic backend-only.
5. ❌ **NEVER access the database directly from the client.** No client-side SQL, no direct Firestore reads.
6. ❌ **NEVER store auth tokens in localStorage unencrypted.** Use secure storage; never log or expose.
7. ❌ **NEVER skip authentication on any API endpoint.** Every endpoint requires validated identity & authorization.
8. ❌ **NEVER return unfiltered error details to the user.** Hide stack traces, SQL queries, internal IDs.
9. ❌ **NEVER store secrets anywhere except GCP Secret Manager.** No committed env secrets, no alternate secret vaults, no hardcoded credentials.
10. ❌ **NEVER change canonical production domains casually.** Keep frontend on `core.tuskus.com` and API on `api.tuskus.com` unless explicitly directed.

### Cross-Platform & Holistic (Non-Negotiable)

11. ❌ Never merge code that builds on one platform but breaks another. "Web only for now" is not acceptable without an explicit, user-approved feature flag.
12. ❌ Never import a native-only module at the top level of a file that the web bundle loads. Use dynamic import + `Platform.OS` guard, or `.native.tsx` split.
13. ❌ Never hardcode platform assumptions (`window`, `document`, `AsyncStorage`, `localStorage`) without a guard or shim.
14. ❌ Never edit one screen/component in isolation when shared code (theme, navigation, API client) would serve all three platforms.
15. ❌ Never make frontend changes without understanding the full backend API contract, database models, and authentication flow. Frontend + backend must change together.
16. ❌ Never implement a feature that only works on frontend without ensuring the backend supports it end-to-end.

### Mandatory Verification

17. ✅ Always add or update tests for the touched module (frontend AND backend).
18. ✅ Always state platform & backend verification status in the final summary, even if "not run locally because X".
19. ✅ Always verify that frontend changes align with backend API expectations and do not break any services or integrations.
20. ✅ Always remove unused imports, variables, functions, types, files, routes, pages, and components introduced or uncovered by the task.
21. ✅ Always remove abandoned/legacy implementations and stale references in the same change.
22. ✅ Always reuse shared components/hooks/utils where possible; avoid near-duplicate implementations.
23. ✅ Always keep code concise and maintainable by extracting repeated logic/UI into shared abstractions.
24. ✅ Always use shared assets/tokens/constants; avoid copying or re-adding the same assets in multiple places.

---

## Anti-Patterns to Reject

### Backend-Driven Architecture Violations

- Frontend business logic → ❌ all calculations, aggregations, authorization must be backend
- Frontend-only validation → ❌ backend is the source of truth
- Exposing database schema to frontend → ❌ use clean DTOs hiding internal structure
- Secrets in frontend code → ❌ never, use backend for all sensitive operations
- Secrets outside GCP Secret Manager → ❌ every secret must live in Google Cloud Secret Manager
- Direct database access from client → ❌ all data access through backend APIs
- Unencrypted tokens in localStorage → ❌ use secure storage; never expose in logs
- Unauthenticated API endpoints → ❌ every endpoint requires verified identity & authorization
- Detailed error messages to users → ❌ hide stack traces, SQL queries, internal IDs
- Changing `core.tuskus.com` or `api.tuskus.com` casually → ❌ preserve canonical production domains unless explicitly directed

### Cross-Platform & Holistic Violations

- "It works on web, ship it" → ❌ verify native too.
- Copy-pasting a component into `web/` and `mobile/` folders → ❌ unify under shared `src/` with platform splits only where necessary.
- Building similar UI separately on multiple screens → ❌ extract a shared reusable component and reuse it.
- Adding a library without checking its web support → ❌ check the package's README/peer-deps first.
- Ignoring `tsc`/lint errors on one platform → ❌ all platforms must pass.
- Editing a single file when the change affects 5 routes → ❌ do the full sweep.
- Duplicating assets/constants/styles per feature folder → ❌ keep shared assets centralized and reused.
- Making frontend changes without checking backend → ❌ always understand the full API contract and database impact.
- Assuming the backend already supports a feature → ❌ verify API endpoints, schemas, and business logic exist and align.
- Merging frontend code without corresponding backend updates → ❌ frontend and backend changes must be coordinated and tested together.

---

## Quick Reference: Recommended Libraries (all have web + iOS + Android support)

| Need                 | Library                                                                                             |
| -------------------- | --------------------------------------------------------------------------------------------------- |
| Routing / deep links | `expo-router`                                                                                       |
| State                | `zustand` or `@tanstack/react-query`                                                                |
| Forms                | `react-hook-form` + `zod`                                                                           |
| Styling              | `nativewind` (Tailwind for RN+web) or StyleSheet                                                    |
| Icons                | `@expo/vector-icons` / `lucide-react-native`                                                        |
| Storage              | `expo-secure-store` (secrets) + `@react-native-async-storage/async-storage` (with web shim)         |
| Auth                 | `expo-auth-session`                                                                                 |
| Notifications        | `expo-notifications` (web fallback required)                                                        |
| Camera/Media         | `expo-camera`, `expo-image-picker`, `expo-image`                                                    |
| Testing              | `jest` + `@testing-library/react-native` + `playwright` (web e2e) + `detox` or Maestro (native e2e) |

Prefer this list. Justify any deviation in the PR description.
