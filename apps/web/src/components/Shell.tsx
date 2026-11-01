"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/SessionProvider";
import { Badge } from "@/components/ui";

const NAV = [
  { href: "/dashboard", label: "Overview" },
  { href: "/datasets", label: "Datasets" },
  { href: "/upload", label: "Import data", roles: ["owner", "analyst"] },
  { href: "/forecasts", label: "Forecasts" },
  { href: "/planning", label: "Planning" },
  { href: "/alerts", label: "Alerts" },
  { href: "/audit", label: "Audit", roles: ["owner"] },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { session, switchOrg, logout } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const [switching, setSwitching] = useState(false);
  const [menuError, setMenuError] = useState<string | null>(null);

  if (!session) return null;

  const role = session.role ?? "viewer";
  const items = NAV.filter((item) => !item.roles || item.roles.includes(role));

  const onSwitch = async (event: React.ChangeEvent<HTMLSelectElement>) => {
    setSwitching(true);
    setMenuError(null);
    try {
      await switchOrg(Number(event.target.value));
      router.refresh();
    } catch (caught) {
      setMenuError(caught instanceof Error ? caught.message : "Could not switch organization.");
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="rail">
        <Link className="brand" href="/dashboard">
          <span className="brand-mark" aria-hidden="true">
            FO
          </span>
          <span>
            ForecastOps
            <span className="brand-sub">Demand &amp; inventory</span>
          </span>
        </Link>
        <nav className="rail-nav" aria-label="Primary">
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={pathname === item.href || pathname.startsWith(`${item.href}/`) ? "page" : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="rail-footer">
          <div className="rail-user">
            <strong>{session.user.display_name}</strong>
            <span>{session.user.email}</span>
            <span style={{ textTransform: "capitalize" }}>Role: {role}</span>
            {session.user.is_demo ? <Badge tone="teal">Demo account</Badge> : null}
          </div>
          <button className="button small" type="button" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-context">
            <span>Workspace</span>
            <strong>{session.active_org?.name ?? "No organization"}</strong>
          </div>
          <div className="topbar-actions">
            {session.organizations.length > 1 ? (
              <label className="field" style={{ minWidth: 190 }}>
                <span className="sr-only">Switch organization</span>
                <select
                  value={session.active_org?.id ?? ""}
                  onChange={(event) => void onSwitch(event)}
                  disabled={switching}
                  aria-label="Switch organization"
                >
                  {session.organizations.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <Badge tone="info">Synthetic demo data only</Badge>
          </div>
        </header>
        {menuError ? (
          <div className="content" style={{ paddingBottom: 0 }}>
            <div className="notice danger" role="alert">
              {menuError}
            </div>
          </div>
        ) : null}
        <main className="content" id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
