"use client";

// Landing page after sign-in. The prototype ALSAC account renders from
// sessionStorage with no backend; real accounts load from /api/me, and a
// failed /me sends the visitor back to /login.
import { useEffect, useLayoutEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { apiFetch, type User } from "@/lib/api";
import { DEMO_USER, hasDemoSession } from "@/lib/demo-auth";
import { Nav } from "@/components/nav";

interface Destination {
  href: string;
  title: string;
  description: string;
}

interface Session {
  user: User;
  demo: boolean;
}

// the prototype account first, then the Flask session; rejects when neither exists
async function loadSession(): Promise<Session> {
  if (hasDemoSession()) return { user: DEMO_USER, demo: true };
  return { user: await apiFetch<User>("/api/me"), demo: false };
}

export default function DashboardPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    // runs again each time the page is shown, since Cache Components only hides
    // it on navigation; that keeps a signed-out visitor from seeing it
    let cancelled = false;
    loadSession()
      .then((s) => {
        if (!cancelled) setSession(s);
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  useLayoutEffect(() => {
    // forget who was signed in while hidden, so a later visitor never sees them
    return () => setSession(null);
  }, []);

  if (!session) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-zinc-500 dark:text-zinc-400">
        Loading…
      </div>
    );
  }

  const { user, demo } = session;
  const destinations: Destination[] = [
    {
      href: "/ask",
      title: "Ask Danny",
      description: "Ask a question and see which documents the answer came from.",
    },
    {
      href: "/files",
      title: "Documents",
      description: "Upload files and choose which teams can see them.",
    },
    ...(user.isAdmin
      ? [{ href: "/admin", title: "Admin", description: "Usage, users and groups." }]
      : []),
  ];

  return (
    <div className="flex min-h-full flex-1 flex-col bg-zinc-50 dark:bg-zinc-950">
      <Nav user={user} />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Welcome, {user.username}
        </h1>
        <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
          Ask questions about your team&apos;s documents and get answers that cite their sources.
        </p>

        {demo && (
          <p className="mt-6 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            You&apos;re using the prototype account. Chat and documents start working once the
            backend and its database are running.
          </p>
        )}

        <ul className="mt-8 divide-y divide-zinc-200 overflow-hidden rounded-lg border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
          {destinations.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="group flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-zinc-50 focus-visible:bg-zinc-50 focus-visible:outline-none dark:hover:bg-zinc-800/60 dark:focus-visible:bg-zinc-800/60"
              >
                <span>
                  <span className="block font-medium text-zinc-900 dark:text-zinc-50">
                    {item.title}
                  </span>
                  <span className="mt-0.5 block text-sm text-zinc-500 dark:text-zinc-400">
                    {item.description}
                  </span>
                </span>
                <span
                  aria-hidden
                  className="text-zinc-400 transition-transform group-hover:translate-x-0.5 dark:text-zinc-500"
                >
                  ›
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
