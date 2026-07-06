"use client";

import { useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { UserButton } from "@clerk/nextjs";
import { SynqLogo } from "@/components/synq-logo";
import { ConversationSidebar } from "@/components/conversation-sidebar";

/**
 * Shared dark app shell for /chat and /dashboard: a 264px sidebar on
 * desktop, collapsing to a slide-in drawer on mobile (< md). This is what
 * makes the app usable on a phone — previously the sidebar (and therefore
 * navigation between conversations / the dashboard) simply didn't render
 * below the md breakpoint.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="flex h-[100dvh] w-screen overflow-hidden bg-bg">
      {/* Mobile topbar — only the entry point for the drawer on small screens */}
      <div className="fixed inset-x-0 top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-bg2 px-4 md:hidden">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open menu"
          className="rounded-lg p-2 text-dim hover:bg-panel hover:text-ink"
        >
          <Menu className="h-5 w-5" />
        </button>
        <Link href="/">
          <SynqLogo size="text-sm" />
        </Link>
        <UserButton afterSignOutUrl="/" />
      </div>

      {/* Backdrop (mobile only, shown while drawer is open) */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar: static column on desktop, slide-in drawer on mobile */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[264px] shrink-0 flex-col border-r border-line bg-bg2 transition-transform duration-200 md:static md:z-auto md:translate-x-0 ${
          drawerOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-4">
          <Link href="/" onClick={() => setDrawerOpen(false)}>
            <SynqLogo size="text-base" />
          </Link>
          <div className="flex items-center gap-1">
            <div className="hidden md:block">
              <UserButton afterSignOutUrl="/" />
            </div>
            <button
              type="button"
              onClick={() => setDrawerOpen(false)}
              aria-label="Close menu"
              className="rounded-lg p-1.5 text-dim hover:bg-panel hover:text-ink md:hidden"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <ConversationSidebar onNavigate={() => setDrawerOpen(false)} />
      </aside>

      <main className="flex flex-1 flex-col overflow-hidden pt-14 md:pt-0">{children}</main>
    </div>
  );
}
