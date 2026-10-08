"use client";

// Top nav shared by the authenticated pages. The Admin link only renders for
// admins; logout clears the Flask session via the API, not just local state.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { apiFetch, type User } from "@/lib/api";

export function Nav({ user }: { user: User | null }) {
  const pathname = usePathname();
  const router = useRouter();

  // user is null while /api/me is still loading — links render immediately,
  // the Admin link just appears a beat later once we know the role
  const links = [
    { href: "/ask", label: "Ask" },
    { href: "/files", label: "Files" },
    ...(user?.isAdmin ? [{ href: "/admin", label: "Admin" }] : []),
  ];

  async function logout() {
    // tell Flask to clear the session server-side; ignore failures — a dead
    // session still ends with the user on /login, which is the goal anyway
    await apiFetch("/api/logout", { method: "POST" }).catch(() => {});
    router.push("/login");
  }

  return (
    <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-3 dark:border-zinc-800">
      {/* brand + page links (current page underlined) */}
      <div className="flex items-center gap-6">
        <span className="font-semibold tracking-tight">Ask Danny</span>
        <nav className="flex gap-4 text-sm">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={
                pathname.startsWith(link.href)
                  ? "font-medium text-black underline underline-offset-4 dark:text-zinc-50"
                  : "text-zinc-500 hover:text-black dark:text-zinc-400 dark:hover:text-zinc-50"
              }
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
      {/* who you're signed in as + sign out */}
      <div className="flex items-center gap-3 text-sm text-zinc-500 dark:text-zinc-400">
        {user && (
          <span>
            {user.username}
            {user.isAdmin ? " (admin)" : ""}
          </span>
        )}
        <button
          onClick={logout}
          className="rounded border border-zinc-300 px-3 py-1 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
