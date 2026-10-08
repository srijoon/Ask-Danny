"use client";

// Signs in through POST /api/login. The response carries a fresh CSRF token —
// login clears the session server-side, so the pre-login token is dead.
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { apiFetch, setCsrfToken, type User } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // already signed in? skip the form
    apiFetch<User>("/api/me")
      .then(() => router.replace("/ask"))
      .catch(() => {});
  }, [router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch<{ user: User; csrfToken: string }>("/api/login", {
        method: "POST",
        json: { username, password },
      });
      // swap in the post-login token — the old one was invalidated when the
      // server cleared the session
      setCsrfToken(res.csrfToken);
      router.push("/ask");
    } catch (err) {
      // a 401 here is wrong credentials — the backend deliberately says
      // "invalid username or password" for both unknown users and bad
      // passwords, so there's no more detail to show
      setError(err instanceof Error ? err.message : "Login failed");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center">
      <main className="w-full max-w-sm rounded-lg border border-zinc-200 p-8 dark:border-zinc-800">
        <h1 className="text-2xl font-semibold tracking-tight">Ask Danny</h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Sign in to search your team&apos;s documents.
        </p>
        {/* the form posts to /api/login — the session cookie does the rest */}
        <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              className="rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className="rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700"
            />
          </label>
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-black px-3 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-black dark:hover:bg-zinc-200"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>
    </div>
  );
}
