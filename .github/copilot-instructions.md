# CoreAdmin Copilot Instructions

## Repository Scope Guard (Mandatory)

- This repository (`CoreAdmin`) is the only implementation target.
- The `Core` repository is read-only reference material.
- Do not modify files in `Core` unless explicit, written approval is provided in the current request.

## Secret Policy (Mandatory)

- Secret values must be sourced only from Google Cloud Secret Manager.
- Never store secret values in source code, `.env` files, frontend code, logs, or test fixtures.
- Environment variables may contain non-secret configuration only (project ID, secret IDs, runtime flags).
- Backend startup must fail fast if required GCP secrets are unavailable.

## Architecture Rules

- Keep CoreAdmin fully independent from Core.
- No shared runtime resources with Core.
- Use Firebase project `core-admin-tuskus` for CoreAdmin resources.
- Keep business logic and entitlement enforcement in backend APIs.

## Security and Quality Gates

- Validate all inputs in backend.
- Enforce authentication/authorization on protected routes.
- Never trust frontend-calculated pricing, entitlement, or workflow state.
- Use idempotency for payment/subscription mutations.
- Verify and deduplicate payment webhooks.
- Run Snyk code scan for newly added or modified first-party code.
