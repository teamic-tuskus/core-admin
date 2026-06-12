"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { CoreBrand } from "@/components/core-brand";
import {
  acceptPortalAccessInvitationByToken,
} from "@/lib/api-client";
import { decodeTokenClaims, getFirstAccessibleRoute } from "@/lib/access";

const CLAIM_PROPAGATION_RETRY_DELAYS_MS = [300, 500, 800, 1200, 1800];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function extractAuthErrorCode(error: unknown): string {
  if (!error || typeof error !== "object") {
    return "";
  }
  const code = (error as { code?: unknown }).code;
  return typeof code === "string" ? code.toLowerCase() : "";
}

function mapAuthError(error: unknown): string {
  if (!error || typeof error !== "object") {
    return "Unable to continue onboarding. Please try again.";
  }

  const code = extractAuthErrorCode(error);
  if (code.includes("email-already-in-use")) {
    return "Account already exists. Switch to Sign in or use Reset password.";
  }
  if (code.includes("invalid-email")) {
    return "Enter a valid email address.";
  }
  if (code.includes("weak-password")) {
    return "Password is too weak. Use at least 6 characters.";
  }
  if (code.includes("invalid-credential") || code.includes("wrong-password") || code.includes("user-not-found")) {
    return "Invalid credentials. Check email/password or use Reset password.";
  }

  return "Unable to continue onboarding. Please try again.";
}

function mapInvitationFlowError(error: unknown): string {
  const message = error instanceof Error ? error.message : "";
  if (
    message.includes("Invitation not found")
    || message.includes("Invitation token is invalid or expired")
    || message.includes("Invitation is no longer actionable")
    || message.includes("Invitation expired")
  ) {
    return "This invitation link is already used, expired, or invalid. Ask an admin to resend a fresh invitation.";
  }
  if (message.includes("Only the invited user can respond")) {
    return "This invitation belongs to a different email. Sign in with the invited email.";
  }
  return message || "Unable to activate invitation.";
}

function InviteOnboardingPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const {
    token,
    loading,
    error,
    refreshToken,
    createUserWithEmailPassword,
    signOutUser,
  } = useAuth();

  const portalToken = searchParams.get("portalToken");
  const inviteeEmailFromUrl = (searchParams.get("inviteeEmail") || "").trim().toLowerCase();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const autoActivationStartedRef = useRef(false);

  const hasInviteId = Boolean(portalToken);

  const controlsDisabled = submitting || loading || !hasInviteId;

  const buildSigninRetryUrl = useCallback(() => {
    const nextParams = new URLSearchParams();
    if (portalToken) {
      nextParams.set("portalToken", portalToken);
    }
    if (inviteeEmailFromUrl) {
      nextParams.set("inviteeEmail", inviteeEmailFromUrl);
    }
    const query = nextParams.toString();
    return query ? `/?${query}` : "/";
  }, [inviteeEmailFromUrl, portalToken]);

  const waitForAccessibleRoute = useCallback(async (startingToken: string) => {
    const initialRoute = getFirstAccessibleRoute(decodeTokenClaims(startingToken));
    if (initialRoute !== "/") {
      return initialRoute;
    }

    for (const retryDelayMs of CLAIM_PROPAGATION_RETRY_DELAYS_MS) {
      await delay(retryDelayMs);
      const refreshedToken = await refreshToken();
      if (!refreshedToken) {
        continue;
      }
      const route = getFirstAccessibleRoute(decodeTokenClaims(refreshedToken));
      if (route !== "/") {
        return route;
      }
    }

    return null;
  }, [refreshToken]);

  const handleAlreadyUsedOrInvalidInvitation = useCallback(async (activeToken: string | null) => {
    const route = activeToken ? await waitForAccessibleRoute(activeToken) : null;
    if (route) {
      setNotice("Invitation already activated. Redirecting to your dashboard...");
      router.replace(route);
      return;
    }
    await signOutUser();
    autoActivationStartedRef.current = false;
    setNotice(null);
    setLocalError("Invitation activation could not be finalized. Please ask an admin to resend access and sign in again.");
  }, [router, signOutUser, waitForAccessibleRoute]);

  const finishOnboarding = useCallback(async (activeToken: string) => {
    if (!portalToken) {
      throw new Error("Missing invitation id.");
    }
    await acceptPortalAccessInvitationByToken(portalToken, activeToken);
    // Firebase custom claims propagation can lag after acceptance.
    const route = await waitForAccessibleRoute(activeToken);
    if (route) {
      setNotice("Access activated. Redirecting to dashboard...");
      router.replace(route);
      return;
    }

    setNotice("Access activation is taking longer than expected. Redirecting to sign in to continue...");
    router.replace(buildSigninRetryUrl());
  }, [buildSigninRetryUrl, portalToken, router, waitForAccessibleRoute]);

  useEffect(() => {
    if (!token || !portalToken || autoActivationStartedRef.current) {
      return;
    }
    autoActivationStartedRef.current = true;
    setSubmitting(true);
    setLocalError(null);
    setNotice("Finalizing invitation access...");

    void (async () => {
      try {
        await finishOnboarding(token);
      } catch (submitError) {
        const fallback = mapInvitationFlowError(submitError);
        if (fallback.includes("already used, expired, or invalid")) {
          await handleAlreadyUsedOrInvalidInvitation(token);
        } else {
          setLocalError(fallback);
        }
      } finally {
        setSubmitting(false);
      }
    })();
  }, [finishOnboarding, handleAlreadyUsedOrInvalidInvitation, portalToken, token]);

  const redirectExistingAccountToSignin = useCallback(async (normalizedEmail: string) => {
    await signOutUser();
    setNotice("Account already exists. Redirecting to sign in...");
    const nextParams = new URLSearchParams({ inviteeEmail: normalizedEmail });
    nextParams.set("portalToken", portalToken || "");
    router.replace(`/?${nextParams.toString()}`);
  }, [portalToken, router, signOutUser]);

  const handleAuthAndAcceptFailure = useCallback(async (
    submitError: unknown,
    normalizedEmail: string,
    idToken: string | null,
  ) => {
    const authCode = extractAuthErrorCode(submitError);
    const message = submitError instanceof Error ? submitError.message : mapAuthError(submitError);
    if (authCode.includes("email-already-in-use") || message.toLowerCase().includes("account already exists")) {
      await redirectExistingAccountToSignin(normalizedEmail);
      return;
    }

    autoActivationStartedRef.current = false;
    if (message.includes("Invitation") || message.includes("invitation")) {
      const fallback = mapInvitationFlowError(submitError);
      if (fallback.includes("already used, expired, or invalid")) {
        await handleAlreadyUsedOrInvalidInvitation(idToken);
      } else {
        setLocalError(fallback);
      }
      return;
    }

    setLocalError(mapAuthError(submitError));
  }, [handleAlreadyUsedOrInvalidInvitation, redirectExistingAccountToSignin]);

  const handleAuthAndAccept = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!portalToken) {
      setLocalError("Invitation link is invalid. Request a fresh invitation.");
      return;
    }

    const normalizedEmail = inviteeEmailFromUrl;
    if (!normalizedEmail) {
      setLocalError("Invitation link is missing invitee details. Request a fresh invitation.");
      return;
    }
    if (!password) {
      setLocalError("Password is required.");
      return;
    }

    if (password !== confirmPassword) {
      setLocalError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    setLocalError(null);
    setNotice(null);
    autoActivationStartedRef.current = true;
    let idToken: string | null = null;

    try {
      idToken = await createUserWithEmailPassword(normalizedEmail, password);
      await finishOnboarding(idToken);
    } catch (submitError) {
      await handleAuthAndAcceptFailure(submitError, normalizedEmail, idToken);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-shell auth-shell-clean">
      <article className="auth-card auth-card-clean">
        <CoreBrand subtitle="Invite Onboarding" />
        <h2>Set your password</h2>
        <p className="subtle">Create a password to activate your invited account, then sign in to continue.</p>
        {hasInviteId ? null : <p className="subtle auth-error">Invitation link is invalid.</p>}

        {token ? (
          <div className="form-grid">
            <p className="subtle">Signed in. Activating your invitation automatically...</p>
          </div>
        ) : (
          <form className="form-grid" onSubmit={handleAuthAndAccept}>
            <label className="subtle" htmlFor="invite-password">
              New password
            </label>
            <input
              id="invite-password"
              type="password"
              autoComplete="new-password"
              className="input"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Create password"
              disabled={controlsDisabled}
            />

            <label className="subtle" htmlFor="invite-confirm-password">
              Confirm password
            </label>
            <input
              id="invite-confirm-password"
              type="password"
              autoComplete="new-password"
              className="input"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Confirm password"
              disabled={controlsDisabled}
            />

            <button className="button" type="submit" disabled={controlsDisabled}>
              {submitting ? "Setting password..." : "Set password"}
            </button>
          </form>
        )}

        {error ? <p className="subtle auth-error">{error}</p> : null}
        {localError ? <p className="subtle auth-error">{localError}</p> : null}
        {notice ? <p className="subtle status-success">{notice}</p> : null}
      </article>
    </div>
  );
}

export default function InviteOnboardingPage() {
  return (
    <Suspense fallback={<div className="auth-shell auth-shell-clean"><article className="auth-card auth-card-clean"><p className="subtle">Loading invitation...</p></article></div>}>
      <InviteOnboardingPageContent />
    </Suspense>
  );
}
