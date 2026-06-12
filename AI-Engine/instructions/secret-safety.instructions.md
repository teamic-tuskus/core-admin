---
description: "Use when creating or editing code, config, docs, scripts, or CI files where credentials might appear. Enforce strict secret safety: never store passwords in files, immediately remove exposed secrets, and migrate to approved secure secret storage."
name: "Secret Safety and Password Handling"
applyTo: "**"
---

# Secret Safety and Password Handling

- Never store passwords, API keys, tokens, private keys, OTP seeds, or connection secrets in source files, docs, logs, fixtures, comments, test data, or commit messages.
- If a secret is discovered during edits, treat it as a security incident in the current task.
- Remove exposed secret values from files immediately.
- Replace hardcoded values with runtime retrieval from approved secret storage.
- For CoreAdmin, approved secret storage is GCP Secret Manager.
- Do not print raw secret values in terminal output or assistant responses.
- If secure migration cannot be fully completed in-session, remove exposure now, add secure placeholders/references, and report exact operational follow-up.

## Required Secret Check Before Completion

- Confirm touched files contain no embedded secret values.
- Confirm any prior exposure in touched files has been removed.
- Confirm runtime secret references point to approved secure storage.