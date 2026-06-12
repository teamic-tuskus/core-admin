"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, type FormEvent, useEffect, useState } from "react";

import { CoreBrand } from "@/components/core-brand";
import { useAuth } from "@/components/auth-provider";
import { decodeTokenClaims, getFirstAccessibleRoute } from "@/lib/access";

function buildInviteRedirectUrl(portalToken: string, inviteeEmail: string): string {
  const nextParams = new URLSearchParams();
  nextParams.set("portalToken", portalToken);
  if (inviteeEmail) {
    nextParams.set("inviteeEmail", inviteeEmail);
  }
  return `/invite?${nextParams.toString()}`;
}

function validateCredentials(email: string, password: string): string | null {
  if (!email.trim() || !password) {
    return "Email and password are required.";
  }
  return null;
}

function getSubmitLabel(submitting: boolean, hasToken: boolean): string {
  if (submitting) return "Signing in...";
  if (hasToken) return "Redirecting...";
  return "Sign in";
}

function AuthPageContent() {
  const { token, loading, error, signInWithEmailPassword, signOutUser } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const portalToken = searchParams.get("portalToken");
  const inviteeEmail = (searchParams.get("inviteeEmail") || "").trim().toLowerCase();
  const passwordSet = searchParams.get("passwordSet") === "1";
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [email, setEmail] = useState(inviteeEmail);
  const [password, setPassword] = useState("");

  const authUnavailable = Boolean(error) && loading === false;
  const controlsDisabled = submitting || Boolean(token) || authUnavailable;

  useEffect(() => {
    if (!loading && token) {
      if (portalToken) {
        router.replace(buildInviteRedirectUrl(portalToken, inviteeEmail));
        return;
      }
      const claims = decodeTokenClaims(token);
      const destination = getFirstAccessibleRoute(claims);
      if (destination === "/") {
        void (async () => {
          await signOutUser();
          setLocalError("Access setup is still in progress. Please reopen your invitation link or contact CoreAdmin support.");
        })();
        return;
      }
      router.replace(destination);
    }
  }, [inviteeEmail, loading, portalToken, router, signOutUser, token]);

  const handleSignIn = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLocalError(null);
    const validationError = validateCredentials(email, password);
    if (validationError) {
      setLocalError(validationError);
      return;
    }

    const trimmedEmail = email.trim();

    setSubmitting(true);
    try {
      await signInWithEmailPassword(trimmedEmail, password);
    } catch {
      setLocalError("Invalid credentials or access not granted. Please contact the CoreAdmin administrator.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-shell auth-shell-clean">
      <article className="auth-card auth-card-clean">
        <CoreBrand subtitle="Admin Portal" />
        <h1>Sign in</h1>
        {passwordSet ? <p className="subtle status-success" role="status" aria-live="polite">Password set successfully. Sign in to continue your invitation.</p> : null}
        {portalToken ? <p className="subtle" role="status" aria-live="polite">Invitation detected. Sign in to continue onboarding.</p> : null}
        <form className="form-grid" onSubmit={handleSignIn}>
          <label className="subtle" htmlFor="email">
            Work email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            className="input"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@company.com"
            disabled={controlsDisabled}
          />

          <label className="subtle" htmlFor="password">
            Password
          </label>
          <div className="password-field">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              className="input"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter your password"
              disabled={controlsDisabled}
            />
            <button
              type="button"
              className="password-toggle-icon"
              onClick={() => setShowPassword((current) => !current)}
              disabled={controlsDisabled}
              aria-label={showPassword ? "Hide password" : "Show password"}
              title={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? (
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path
                    d="M4 4l16 16M10.6 10.6a2 2 0 102.8 2.8M9.9 5.6A11 11 0 0112 5c5 0 9 4.5 10 7-0.4 1-1.4 2.6-3 4M6.3 8.1C4.8 9.3 3.7 10.7 3 12c1 2.5 5 7 10 7 1.3 0 2.5-0.3 3.6-0.7"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path
                    d="M2 12c1-2.5 5-7 10-7s9 4.5 10 7c-1 2.5-5 7-10 7S3 14.5 2 12z"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
                </svg>
              )}
            </button>
          </div>

          <button className="button" type="submit" disabled={controlsDisabled}>
            {getSubmitLabel(submitting, Boolean(token))}
          </button>
          {loading && !token ? <p className="subtle" role="status" aria-live="polite">Checking secure session…</p> : null}
          {authUnavailable ? <p className="subtle auth-error" role="alert">Authentication service is unavailable. Please try again shortly.</p> : null}
          {!authUnavailable && error ? <p className="subtle auth-error" role="alert">{error}</p> : null}
          {localError ? <p className="subtle auth-error" role="alert">{localError}</p> : null}
        </form>
      </article>
    </div>
  );
}

export function AuthPageView() {
  return (
    <Suspense fallback={<div className="auth-shell auth-shell-clean"><article className="auth-card auth-card-clean"><p className="subtle">Loading secure session...</p></article></div>}>
      <AuthPageContent />
    </Suspense>
  );
}
