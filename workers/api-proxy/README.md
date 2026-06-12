# CoreAdmin API Proxy

This Cloudflare Worker keeps the public API hostname `api.tuskus.com` while routing traffic to the correct backend.

## Purpose

- Receives browser requests on `api.tuskus.com`
- Adds CORS headers for `core.tuskus.com` and local development origins
- Routes sales/onboarding endpoints to CoreAdmin backend
- Routes CoreAdmin portal-origin requests to CoreAdmin backend
- Routes all other API traffic to Core backend

## Deploy

```bash
cd workers/api-proxy
wrangler deploy
```

## Backend Targets

- CoreAdmin: `https://coreadmin-backend-908245778962.asia-south1.run.app`
- Core: `https://core-api-bgqab4t4dq-el.a.run.app`
