"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

function getInitials(email: string | null | undefined): string {
  if (!email) {
    return "AD";
  }

  const [localPart] = email.split("@");
  if (!localPart) {
    return "AD";
  }

  const parts = localPart.split(/[._-]+/).filter(Boolean);
  if (!parts.length) {
    return localPart.slice(0, 2).toUpperCase();
  }

  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }

  return `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}`.toUpperCase();
}

function toTitleCase(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((item) => item[0].toUpperCase() + item.slice(1).toLowerCase())
    .join(" ");
}

function getDisplayName(displayName: string | null | undefined, email: string | null | undefined): string {
  if (displayName?.trim()) {
    return displayName.trim();
  }

  if (!email) {
    return "Admin User";
  }

  const localPart = email.split("@")[0] || "";
  if (!localPart) {
    return "Admin User";
  }

  return toTitleCase(localPart.replace(/[._-]+/g, " "));
}

export function ProfileAvatarLink() {
  const router = useRouter();
  const { user, loading, signOutUser } = useAuth();
  const initials = getInitials(user?.email || null);
  const displayName = getDisplayName(user?.displayName, user?.email);

  const handleLogout = async () => {
    await signOutUser();
    router.replace("/");
  };

  if (!user) {
    return null;
  }

  return (
    <div className="profile-account">
      <div className="profile-summary-card">
        <Link href="/profile" className="profile-summary-link" aria-label="Open profile" title="Profile">
          <span className="profile-avatar" aria-hidden="true">
            {initials}
          </span>
          <span className="profile-meta">
            <span className="profile-name">{displayName}</span>
            <span className="profile-email">Profile</span>
          </span>
        </Link>
        <button
          className="profile-logout-icon"
          type="button"
          onClick={handleLogout}
          disabled={loading}
          aria-label="Logout"
          title={loading ? "Signing out..." : "Logout"}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M10.5 4.5h-3A2.5 2.5 0 0 0 5 7v10a2.5 2.5 0 0 0 2.5 2.5h3" />
            <path d="M14 8.5 18.5 12 14 15.5" />
            <path d="M18 12H9" />
          </svg>
        </button>
      </div>
    </div>
  );
}
