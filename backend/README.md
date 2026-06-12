# CoreAdmin Backend

## Secret Management Policy (Mandatory)

All secret values must be retrieved from Google Cloud Secret Manager.

- Allowed in environment variables: non-secret configuration only
  - Example: `COREADMIN_GCP_PROJECT_ID`, `COREADMIN_SECRET_IDS`
- Not allowed in environment variables: secret values
  - Example: API keys, signing keys, service account JSON, tokens

Application startup validates required secrets from GCP Secret Manager and fails fast if any are missing.

## Required Configuration

- `COREADMIN_GCP_PROJECT_ID` (required)
- `COREADMIN_GCP_SECRET_VERSION` (optional, default: `latest`)
- `COREADMIN_SECRET_IDS` (optional comma-separated list)
- `COREADMIN_FIREBASE_STORAGE_BUCKET` (optional, enables Firebase Storage integration)

Default required secret IDs:

1. `firebase-service-account-json`
2. `razorpay-key-id`
3. `razorpay-key-secret`
4. `razorpay-webhook-secret`
5. `jwt-signing-key`

SMTP-related secret IDs (required when `COREADMIN_SMTP_ENABLED=true`):

1. `smtp-username`
2. `smtp-password`
3. `smtp-from-email`

## SMTP Runtime Configuration

Configure these non-secret values in environment:

- `COREADMIN_SMTP_ENABLED` (`true` / `false`)
- `COREADMIN_SMTP_HOST` (example: `smtp.gmail.com`)
- `COREADMIN_SMTP_PORT` (example: `587`)
- `COREADMIN_SMTP_USE_TLS` (`true` / `false`)
- `COREADMIN_SMTP_TIMEOUT_SECONDS` (example: `15`)
- `COREADMIN_SMTP_FROM_NAME` (example: `Tuskus Core`)
- `COREADMIN_SUPPORT_EMAIL` (example: `support@tuskus.com`)

Optional secret-id overrides:

- `COREADMIN_SMTP_USERNAME_SECRET_ID`
- `COREADMIN_SMTP_PASSWORD_SECRET_ID`
- `COREADMIN_SMTP_FROM_EMAIL_SECRET_ID`

## Run

```bash
pip install -r requirements.txt
COREADMIN_GCP_PROJECT_ID="your-gcp-project" python3 -m uvicorn app.main:app --reload
```

### Local Razorpay Bypass (Non-Production)

To bypass Razorpay during local/staging checkout tests, enable:

```bash
COREADMIN_CHECKOUT_TEST_PAYMENT_BYPASS_ENABLED=true
```

Example:

```bash
COREADMIN_GCP_PROJECT_ID="your-gcp-project" \
COREADMIN_CHECKOUT_TEST_PAYMENT_BYPASS_ENABLED=true \
python3 -m uvicorn app.main:app --reload
```

## Deployment Region

Production deployments must stay in `asia-south1`.

```bash
gcloud run deploy coreadmin-backend \
  --project core-admin-tuskus \
  --region asia-south1 \
  --source .
```
