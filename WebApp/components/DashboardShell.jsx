"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { UserIcon } from "./AgentIcons";

const NAV_ITEMS = [
  { view: "home", label: "Home", href: "/" },
  { view: "properties", label: "My Properties", href: "/?view=properties" },
  { view: "revy", label: "Revy", href: "/?view=revy", icon: "/Revy.png" },
];

export default function DashboardShell({ activeView = "home", activeAccount, email, children }) {
  const router = useRouter();
  const accountName = activeAccount?.name || "RevNest";
  const accountEmail = email || activeAccount?.email || "";

  function go(href) {
    router.push(href);
  }

  return (
    <main className="airbnb-shell">
      <header className="airbnb-topbar">
        <div className="airbnb-topbar-left">
          <button className="airbnb-brand" type="button" onClick={() => go("/")} aria-label="RevNest Home">
            <Image src="/icon.png" alt="" width={34} height={34} />
            <span>RevNest</span>
          </button>
          <nav className="airbnb-topnav" aria-label="Main navigation">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.view}
                className={activeView === item.view ? `active ${item.icon ? "revy-nav-button" : ""}`.trim() : item.icon ? "revy-nav-button" : ""}
                type="button"
                onClick={() => go(item.href)}
                title={item.view === "account" ? accountEmail || accountName : item.label}
              >
                {item.icon ? <Image className="topnav-revy-icon" src={item.icon} alt="" width={20} height={20} /> : null}
                {item.label}
              </button>
            ))}
          </nav>
        </div>
        <div className="airbnb-topbar-right">
          <button
            className={activeView === "account" ? "airbnb-account-button active" : "airbnb-account-button"}
            type="button"
            onClick={() => go("/?view=account")}
            aria-label="Account"
            title={accountEmail || accountName || "Account"}
          >
            <UserIcon width={20} height={20} />
          </button>
        </div>
      </header>

      <section className="airbnb-main">{children}</section>
    </main>
  );
}
