"use client";

import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

export function LogoutButton() {
  const router = useRouter();
  const { user, loading, signOutUser } = useAuth();

  const handleLogout = async () => {
    await signOutUser();
    router.replace("/");
  };

  if (!user) {
    return null;
  }

  return (
    <button className="button secondary" type="button" onClick={handleLogout} disabled={loading}>
      {loading ? "Signing out..." : "Logout"}
    </button>
  );
}
