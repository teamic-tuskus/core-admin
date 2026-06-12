"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

type AuthGateProps = {
  children: React.ReactNode;
};

const PUBLIC_PATHS = new Set(["/", "/invite"]);

export function AuthGate({ children }: Readonly<AuthGateProps>) {
  const { user, token, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isPublicPath = PUBLIC_PATHS.has(pathname);
  const isAuthenticated = Boolean(user && token);

  useEffect(() => {
    if (loading || isPublicPath || isAuthenticated) {
      return;
    }
    router.replace("/");
  }, [isAuthenticated, isPublicPath, loading, router]);

  if (!isPublicPath && (loading || !isAuthenticated)) {
    return null;
  }

  return <>{children}</>;
}
