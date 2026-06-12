"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import { useAuth } from "@/components/auth-provider";
import { CoreBrand } from "@/components/core-brand";
import { ProfileAvatarLink } from "@/components/profile-avatar-link";
import { decodeTokenClaims, getFirstAccessibleRoute, isRouteAllowedByClaims } from "@/lib/access";
import { navItems } from "@/lib/site";

function NavIcon({ href }: Readonly<{ href: string }>) {
  if (href === "/products") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7.75A2.75 2.75 0 0 1 6.75 5h10.5A2.75 2.75 0 0 1 20 7.75v8.5A2.75 2.75 0 0 1 17.25 19H6.75A2.75 2.75 0 0 1 4 16.25z" />
        <path d="M4 10.5h16" />
      </svg>
    );
  }

  if (href === "/coupons" || href === "/coupons/advance") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M8 5h8a3 3 0 0 1 3 3v1.25a1.75 1.75 0 0 0 0 3.5V14a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3v-1.25a1.75 1.75 0 0 0 0-3.5V8a3 3 0 0 1 3-3z" />
        <path d="M10.5 9.5h3" />
        <path d="M10.5 14.5h3" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 12a3.25 3.25 0 1 0-3.25-3.25A3.25 3.25 0 0 0 12 12z" />
      <path d="M6.25 18.5a5.75 5.75 0 0 1 11.5 0" />
    </svg>
  );
}

type PageShellProps = Readonly<{
  title: string;
  eyebrow?: string;
  description: string;
  compactHeader?: boolean;
  headerActions?: React.ReactNode;
  children: React.ReactNode;
}>;

export function PageShell({
  title,
  eyebrow,
  description,
  compactHeader = false,
  headerActions,
  children,
}: Readonly<PageShellProps>) {
  const { token } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const claims = useMemo(() => decodeTokenClaims(token), [token]);

  const filteredNavItems = useMemo(() => {
    return navItems.filter((item) => isRouteAllowedByClaims(item.href, claims));
  }, [claims]);

  useEffect(() => {
    if (!pathname || pathname === "/" || pathname.startsWith("/invite")) {
      return;
    }

    if (isRouteAllowedByClaims(pathname, claims)) {
      return;
    }

    const fallbackPath = getFirstAccessibleRoute(claims);
    if (fallbackPath && fallbackPath !== pathname) {
      router.replace(fallbackPath);
    }
  }, [claims, pathname, router]);

  const isActiveNavItem = (href: string) => {
    if (href === "/coupons") {
      return pathname === "/coupons";
    }
    if (href === "/coupons/advance") {
      return pathname === "/coupons/advance";
    }
    return pathname === href;
  };

  return (
    <div className="shell shell-with-sidebar">
      <header className="app-header">
        <CoreBrand compact subtitle="Admin Portal" />
      </header>

      <div className="app-layout">
        <aside className="sidebar">
          <p className="sidebar-title">Navigation</p>

          <nav className="nav sidebar-nav">
            {filteredNavItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-link ${isActiveNavItem(item.href) ? "nav-link-active" : ""}`.trim()}
              >
                <span className="nav-link-icon" aria-hidden="true">
                  <NavIcon href={item.href} />
                </span>
                <span className="nav-link-copy">
                  <span className="nav-link-label">{item.label}</span>
                  <span className="nav-link-desc">{item.description}</span>
                </span>
              </Link>
            ))}
          </nav>

          <div className="sidebar-footer">
            <ProfileAvatarLink />
          </div>
        </aside>

        <main className="page-grid">
          <section className={`hero ${compactHeader ? "hero-compact" : ""}`.trim()}>
            <div className="hero-head">
              <div className="hero-copy-block">
                {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
                <h1>{title}</h1>
                <p className="hero-copy">{description}</p>
              </div>
              {headerActions ? <div className="hero-actions">{headerActions}</div> : null}
            </div>
          </section>

          {children}
        </main>
      </div>
    </div>
  );
}