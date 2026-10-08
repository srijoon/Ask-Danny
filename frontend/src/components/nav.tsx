"use client";

// Top nav shared by the authenticated pages. The Admin link only renders for
// admins; logout clears the Flask session via the API, not just local state.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { apiFetch, type User } from "@/lib/api";
import { endDemoSession, hasDemoSession } from "@/lib/demo-auth";
import { Wordmark } from "@/components/wordmark";

export function Nav({ user }: { user: User | null }) {
  const pathname = usePathname();
  const router = useRouter();

  // user is null while /api/me is still loading — links render immediately,
  // the Admin link just appears a beat later once we know the role
  const links = [
    { href: "/dashboard", label: "Home" },
    { href: "/ask", label: "Ask" },
    { href: "/files", label: "Files" },
    ...(user?.isAdmin ? [{ href: "/admin", label: "Admin" }] : []),
  ];

  async function logout() {
    // the prototype account has no server session, so just drop the browser
    // flag. otherwise tell Flask to clear the session; ignore failures — a dead
    // session still ends with the user on /login, which is the goal anyway
    if (hasDemoSession()) {
      endDemoSession();
    } else {
      await apiFetch("/api/logout", { method: "POST" }).catch(() => {});
    }
    router.push("/login");
  }

  return (
    // the thin red bar on top carries the brand across every signed-in page
    <header className="border-t-[3px] border-b border-t-brand border-b-zinc-200 bg-white dark:border-b-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-2.5 sm:px-6">
        {/* brand + page links (current page in red) */}
        <div className="flex items-center gap-6">
          <Link href="/dashboard" aria-label="Ask Danny home">
            <Wordmark tone="light" />
          </Link>
          <nav className="flex gap-1 text-sm">
            {links.map((link) => {
              const active = pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={
                    active
                      ? "rounded-md bg-brand-tint px-3 py-1.5 font-medium text-brand dark:bg-red-950/50 dark:text-red-300"
                      : "rounded-md px-3 py-1.5 text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-50"
                  }
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
        </div>
        {/* who you're signed in as + sign out */}
        <div className="flex items-center gap-3 text-sm text-zinc-500 dark:text-zinc-400">
          {user && (
            <span className="hidden sm:inline">
              {user.username}
              {user.isAdmin ? " (admin)" : ""}
            </span>
          )}
          <button
            onClick={logout}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
