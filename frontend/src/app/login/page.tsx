"use client";

// Sign-in. ALSAC / ALSAC opens the prototype dashboard without touching the
// backend (see lib/demo-auth.ts). Anything else goes to POST /api/login, whose
// response carries a fresh CSRF token because login clears the session.
import { useEffect, useLayoutEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { apiFetch, ApiError, setCsrfToken, type User } from "@/lib/api";
import { hasDemoSession, isDemoCredentials, startDemoSession } from "@/lib/demo-auth";
import { Wordmark } from "@/components/wordmark";

const INVALID_CREDENTIALS = "Invalid username or password.";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // already signed in, either way? skip the form
    if (hasDemoSession()) {
      router.replace("/dashboard");
      return;
    }
    apiFetch<User>("/api/me")
      .then(() => router.replace("/dashboard"))
      .catch(() => {});
  }, [router]);

  useLayoutEffect(() => {
    // Cache Components keeps this page alive (hidden) after navigating away, so
    // without this a user coming back after sign-out would find the old
    // password and a stuck "Signing in…" button
    return () => {
      setPassword("");
      setError(null);
      setBusy(false);
    };
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const name = username.trim();
    if (!name || !password) {
      setError("Enter your username and password.");
      return;
    }
    setBusy(true);
    setError(null);

    if (isDemoCredentials(name, password)) {
      if (!startDemoSession()) {
        setError("This browser is blocking site storage, so the session can't be saved. Allow site data and try again.");
        setBusy(false);
        return;
      }
      router.push("/dashboard");
      return;
    }

    try {
      const res = await apiFetch<{ user: User; csrfToken: string }>("/api/login", {
        method: "POST",
        json: { username: name, password },
      });
      // swap in the post-login token; the old one died when the server cleared
      // the session
      setCsrfToken(res.csrfToken);
      router.push("/dashboard");
    } catch (err) {
      // 503 is Flask saying the database is down, which a real user should hear
      // about. Everything else (401, or no backend at all, where the demo
      // account is the only one that exists) reads as bad credentials
      setError(
        err instanceof ApiError && err.status === 503
          ? "Sign-in is unavailable because the document database can't be reached. Try again shortly."
          : INVALID_CREDENTIALS,
      );
      setBusy(false);
    }
  }

  const inputClass =
    "w-full rounded-md border border-zinc-300 bg-white px-3 py-2.5 text-[15px] text-zinc-900 " +
    "outline-none transition-colors placeholder:text-zinc-400 " +
    "focus:border-brand focus:ring-2 focus:ring-brand/20 " +
    "aria-invalid:border-red-500 " +
    "dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50 dark:focus:border-red-400 dark:focus:ring-red-400/20";

  return (
    <div className="flex flex-1 flex-col md:flex-row">
      {/* brand panel: an example of what the product does, a cited answer */}
      <aside className="hidden flex-col justify-between bg-brand-deep px-12 py-12 text-red-50 md:flex md:w-[44%] lg:px-16">
        <Wordmark />

        <div className="max-w-md">
          <h1 className="text-[2.5rem] leading-[1.1] font-semibold tracking-tight text-white">
            Answers from your team&apos;s documents.
          </h1>
          <p className="mt-4 text-base leading-relaxed text-red-100/85">
            Every answer points to the pages it came from, and you only see documents you have
            access to.
          </p>

          <figure className="mt-10 rounded-lg border border-white/15 bg-black/15 p-5 text-sm leading-relaxed">
            <figcaption className="text-xs text-red-100/70">Example question</figcaption>
            <p className="mt-1 font-medium text-white">How many vacation days do new hires get?</p>
            <p className="mt-4 text-red-50">
              New hires get 15 vacation days in their first year
              <Cite n={1} />, which rises to 20 after three years of service
              <Cite n={2} />.
            </p>
            <ol className="mt-4 space-y-1 border-t border-white/15 pt-3 text-xs text-red-100/75">
              <li>
                <span className="font-semibold text-white">[1]</span> Employee Handbook, page 12
              </li>
              <li>
                <span className="font-semibold text-white">[2]</span> Time Off Policy, page 3
              </li>
            </ol>
          </figure>
        </div>

        <p className="text-xs text-red-100/60">For ALSAC staff. Internal use only.</p>
      </aside>

      {/* sign-in form */}
      <main className="flex flex-1 items-center justify-center bg-zinc-50 px-4 py-12 sm:px-8 dark:bg-zinc-950">
        <div className="w-full max-w-sm">
          {/* the brand panel is hidden on small screens, so name the app here */}
          <div className="mb-8 md:hidden">
            <Wordmark tone="light" />
          </div>

          <h2 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            Sign in
          </h2>
          <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
            Use the account your administrator gave you.
          </p>

          <form onSubmit={submit} noValidate className="mt-8 flex flex-col gap-5">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="username" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                Username or ID
              </label>
              <input
                id="username"
                name="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
                required
                disabled={busy}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? "login-error" : undefined}
                className={inputClass}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="password" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                disabled={busy}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? "login-error" : undefined}
                className={inputClass}
              />
            </div>

            {error && (
              <p
                id="login-error"
                role="alert"
                className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="mt-1 flex items-center justify-center gap-2 rounded-md bg-brand px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-60 dark:focus-visible:outline-red-400"
            >
              {busy && (
                <span
                  aria-hidden
                  className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent motion-reduce:animate-none"
                />
              )}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}

// the citation marker from the example answer
function Cite({ n }: { n: number }) {
  return (
    <sup className="ml-0.5 rounded bg-white/20 px-1 text-[0.7rem] font-semibold text-white">{n}</sup>
  );
}
