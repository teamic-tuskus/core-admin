# SMTP Setup (CoreAdmin)

This mirrors the Core app pattern: direct Gmail SMTP using your own
`support@tuskus.com` mailbox (no third-party email app integration).

## 1) Set non-secret runtime config

Set these environment variables in your runtime:

- `COREADMIN_SMTP_ENABLED=true`
- `COREADMIN_SMTP_HOST=smtp.gmail.com`
- `COREADMIN_SMTP_PORT=587`
- `COREADMIN_SMTP_USE_TLS=true`
- `COREADMIN_SMTP_TIMEOUT_SECONDS=15`
- `COREADMIN_SMTP_FROM_NAME=Tuskus Core`
- `COREADMIN_SUPPORT_EMAIL=support@tuskus.com`

## 2) Save SMTP secrets in GCP Secret Manager

Required secrets (project: `core-admin-tuskus`):

- `smtp-username` (use `support@tuskus.com`)
- `smtp-password` (Gmail App Password for support mailbox)
- `smtp-from-email` (example: `noreply@tuskus.com` or `support@tuskus.com`)

## 3) Quick terminal commands

Create secrets if missing:

```bash
gcloud secrets create smtp-username --project core-admin-tuskus --replication-policy=automatic || true
gcloud secrets create smtp-password --project core-admin-tuskus --replication-policy=automatic || true
gcloud secrets create smtp-from-email --project core-admin-tuskus --replication-policy=automatic || true
```

Add secret versions:

```bash
read -p "SMTP username: " SMTP_USER
printf "%s" "$SMTP_USER" | gcloud secrets versions add smtp-username --project core-admin-tuskus --data-file=-
unset SMTP_USER

read -s -p "SMTP password: " SMTP_PASS; echo
printf "%s" "$SMTP_PASS" | gcloud secrets versions add smtp-password --project core-admin-tuskus --data-file=-
unset SMTP_PASS

read -p "From email (noreply@tuskus.com or support@tuskus.com): " SMTP_FROM
printf "%s" "$SMTP_FROM" | gcloud secrets versions add smtp-from-email --project core-admin-tuskus --data-file=-
unset SMTP_FROM
```

Gmail requirement: enable 2-Step Verification and generate an App Password.
Use that App Password as `smtp-password`.

## 4) Startup behavior

When `COREADMIN_SMTP_ENABLED=true`, backend startup validates SMTP secrets and fails fast if missing.

## 5) Code location

SMTP sender implementation:

- `app/services/email_sender.py`
