"use client";

// Read-only admin dashboard over /api/admin/*: usage stats, users, and groups.
// Non-admins get a 403 from the API — we show that instead of a broken table.
import { useEffect, useState } from "react";

import {
  apiFetch,
  ApiError,
  type AdminGroup,
  type AdminUser,
  type Usage,
  type User,
} from "@/lib/api";
import { Nav } from "@/components/nav";

export default function AdminPage() {
  const [user, setUser] = useState<User | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [groups, setGroups] = useState<AdminGroup[]>([]);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<User>("/api/me").then(setUser).catch(() => {});
    // the three admin endpoints are independent — fetch in parallel; a single
    // failure rejects the batch, which is what we want (a 403 from any of them
    // means "not an admin", so partial data is never worth rendering)
    Promise.all([
      apiFetch<Usage>("/api/admin/usage"),
      apiFetch<{ users: AdminUser[] }>("/api/admin/users"),
      apiFetch<{ groups: AdminGroup[] }>("/api/admin/groups"),
    ])
      .then(([usageRes, usersRes, groupsRes]) => {
        setUsage(usageRes);
        setUsers(usersRes.users);
        setGroups(groupsRes.groups);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setForbidden(true);
        else setError(err instanceof Error ? err.message : "Couldn't load admin data");
      });
  }, []);

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <Nav user={user} />
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
        <h1 className="text-lg font-semibold">Admin</h1>

        {/* access errors render as messages, not empty tables */}
        {forbidden && (
          <p className="mt-6 text-sm text-red-600 dark:text-red-400">
            Admin access required.
          </p>
        )}
        {error && <p className="mt-6 text-sm text-red-600 dark:text-red-400">{error}</p>}

        {/* usage cards + the detail line under them */}
        {usage && (
          <section className="mt-6">
            <h2 className="text-sm font-medium text-zinc-600 dark:text-zinc-400">Usage</h2>
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["Documents", usage.documents.count],
                ["Chunks", usage.documents.chunks],
                ["Questions", usage.questions.total],
                ["LLM calls skipped", usage.savings.answerCallsSkipped],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
                >
                  <p className="text-2xl font-semibold">{value}</p>
                  <p className="text-xs text-zinc-500">{label}</p>
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-zinc-500">
              Storage used: {(usage.documents.totalBytes / (1024 * 1024)).toFixed(1)} MB ·
              LLM: {usage.llm} · by status:{" "}
              {Object.entries(usage.questions.byStatus)
                .map(([status, n]) => `${status} ${n}`)
                .join(", ") || "none"}
            </p>
            {Object.keys(usage.questions.byUser).length > 0 && (
              <p className="mt-1 text-xs text-zinc-500">
                by user:{" "}
                {Object.entries(usage.questions.byUser)
                  .map(([name, n]) => `${name} ${n}`)
                  .join(", ")}
              </p>
            )}
          </section>
        )}

        {/* users table */}
        {users.length > 0 && (
          <section className="mt-8">
            <h2 className="text-sm font-medium text-zinc-600 dark:text-zinc-400">Users</h2>
            <table className="mt-2 w-full text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-800">
                  <th className="py-2 font-medium">Username</th>
                  <th className="py-2 font-medium">Groups</th>
                  <th className="py-2 font-medium">Admin</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-zinc-100 dark:border-zinc-900">
                    <td className="py-2">{u.username}</td>
                    <td className="py-2">{u.groups.join(", ") || "—"}</td>
                    <td className="py-2">{u.isAdmin ? "yes" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {/* groups table: name, members, how many documents it can see */}
        {groups.length > 0 && (
          <section className="mt-8">
            <h2 className="text-sm font-medium text-zinc-600 dark:text-zinc-400">Groups</h2>
            <table className="mt-2 w-full text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-800">
                  <th className="py-2 font-medium">Name</th>
                  <th className="py-2 font-medium">Members</th>
                  <th className="py-2 font-medium">Documents</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((grp) => (
                  <tr key={grp.id} className="border-b border-zinc-100 dark:border-zinc-900">
                    <td className="py-2">{grp.name}</td>
                    <td className="py-2">{grp.members.join(", ") || "—"}</td>
                    <td className="py-2">{grp.documentCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </main>
    </div>
  );
}
