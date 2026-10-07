"use client";

import { useEffect, useState } from "react";

type Status =
  | { state: "loading" }
  | { state: "ok"; message: string }
  | { state: "error"; error: string };

export function BackendStatus() {
  const [status, setStatus] = useState<Status>({ state: "loading" });

  useEffect(() => {
    fetch("/api/hello?name=Next.js")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{ message: string }>;
      })
      .then((data) => setStatus({ state: "ok", message: data.message }))
      .catch((err: Error) => setStatus({ state: "error", error: err.message }));
  }, []);

  if (status.state === "loading") {
    return <p className="text-zinc-500">Contacting Flask backend…</p>;
  }

  if (status.state === "error") {
    return (
      <p className="text-red-600 dark:text-red-400">
        Backend unreachable ({status.error}). Is <code>npm run dev:backend</code> running?
      </p>
    );
  }

  return (
    <p className="text-green-700 dark:text-green-400">
      Flask says: <span className="font-mono">{status.message}</span>
    </p>
  );
}
