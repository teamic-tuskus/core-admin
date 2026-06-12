type Env = {
  COREADMIN_BACKEND_ORIGIN: string;
  CORE_BACKEND_ORIGIN: string;
  ALLOWED_ORIGINS: string;
};

const CORS_HEADERS = [
  "access-control-allow-headers",
  "access-control-allow-methods",
  "access-control-allow-origin",
  "access-control-max-age",
  "vary",
] as const;

function buildCorsHeaders(request: Request, env: Env): Headers {
  const headers = new Headers();
  const origin = request.headers.get("Origin") || "";
  const allowedOrigins = env.ALLOWED_ORIGINS.split(",").map((item) => item.trim()).filter(Boolean);
  const allowOrigin = allowedOrigins.includes(origin) ? origin : allowedOrigins[0] || "";

  if (allowOrigin) {
    headers.set("Access-Control-Allow-Origin", allowOrigin);
    headers.set("Vary", "Origin");
  }

  headers.set("Access-Control-Allow-Methods", "GET,POST,PATCH,PUT,DELETE,OPTIONS");
  headers.set("Access-Control-Allow-Headers", request.headers.get("Access-Control-Request-Headers") || "Authorization,Content-Type,X-Idempotency-Key");
  headers.set("Access-Control-Max-Age", "86400");
  return headers;
}

function withCors(response: Response, corsHeaders: Headers): Response {
  const headers = new Headers(response.headers);
  for (const [key, value] of corsHeaders.entries()) {
    headers.set(key, value);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function hostFromUrl(value: string | null): string {
  if (!value) return "";
  try {
    return new URL(value).host.toLowerCase();
  } catch {
    return "";
  }
}

function resolveBackendOrigin(request: Request, env: Env, incomingUrl: URL): string {
  const path = incomingUrl.pathname.toLowerCase();
  if (path.startsWith("/api/v1/sales") || path.startsWith("/api/v1/onboarding")) {
    return env.COREADMIN_BACKEND_ORIGIN;
  }

  const originHost = hostFromUrl(request.headers.get("origin"));
  const refererHost = hostFromUrl(request.headers.get("referer"));
  const fromCoreAdminPortal = originHost === "coreadmin.tuskus.com" || refererHost === "coreadmin.tuskus.com";

  if (fromCoreAdminPortal) {
    return env.COREADMIN_BACKEND_ORIGIN;
  }
  return env.CORE_BACKEND_ORIGIN;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const corsHeaders = buildCorsHeaders(request, env);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    const incomingUrl = new URL(request.url);
  const backendOrigin = resolveBackendOrigin(request, env, incomingUrl);
  const upstreamUrl = new URL(`${backendOrigin}${incomingUrl.pathname}${incomingUrl.search}`);

    const upstreamRequest = new Request(upstreamUrl.toString(), request);
    const upstreamResponse = await fetch(upstreamRequest);
    return withCors(upstreamResponse, corsHeaders);
  },
};
