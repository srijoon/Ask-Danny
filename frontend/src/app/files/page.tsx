"use client";

// File manager over /api/files: list (optionally filtered by pool), upload with
// a pool picker built from /api/me, and delete. Upload errors like 409
// (duplicate) and 422 (unreadable/too long) surface the backend's message.
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { apiFetch, type FileDoc, type User } from "@/lib/api";
import { Nav } from "@/components/nav";

// display-only formatter — the backend always sends raw bytes
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FilesPage() {
  const [user, setUser] = useState<User | null>(null);
  const [files, setFiles] = useState<FileDoc[]>([]);
  const [filterPool, setFilterPool] = useState("");
  const [uploadPool, setUploadPool] = useState("shared");
  const [title, setTitle] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // shared by the mount effect, the pool filter, and post-upload/refresh — a
  // useCallback so upload() can await the same refetch path
  const loadFiles = useCallback(
    async (pool: string) => {
      // "" means "everything I can see" — the API filters by principals server-side
      const query = pool ? `?poolId=${encodeURIComponent(pool)}` : "";
      const res = await apiFetch<{ files: FileDoc[] }>(`/api/files${query}`);
      setFiles(res.files);
    },
    [],
  );

  useEffect(() => {
    apiFetch<User>("/api/me")
      .then(setUser)
      .catch(() => {});
    apiFetch<{ files: FileDoc[] }>("/api/files")
      .then((res) => setFiles(res.files))
      .catch((err) => setError(err instanceof Error ? err.message : "Couldn't load files"));
  }, []);

  async function changeFilter(pool: string) {
    // filtering is a server round-trip, not local — the pool filter is an API
    // parameter, so refetching is what keeps membership rules authoritative
    setFilterPool(pool);
    try {
      await loadFiles(pool);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load files");
    }
  }

  async function upload(e: FormEvent) {
    e.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) {
      setError("Choose a file first.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    const form = new FormData();
    form.append("file", file);
    form.append("poolId", uploadPool);
    if (title.trim()) form.append("title", title.trim());
    try {
      const res = await apiFetch<{ file: FileDoc }>("/api/files", { method: "POST", form });
      // ingestion already ran server-side — the response reports how many
      // chunks it produced, which doubles as a "did my file parse?" check
      setNotice(`Uploaded '${res.file.title}' (${res.file.chunkCount} chunks).`);
      setTitle("");
      if (fileInput.current) fileInput.current.value = "";
      await loadFiles(filterPool);
    } catch (err) {
      // the API's message is already specific (409 duplicate, 415 wrong type,
      // 422 unreadable) — show it verbatim rather than masking it
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove(doc: FileDoc) {
    // deletion is permanent and removes every stored chunk — worth a confirm
    if (!window.confirm(`Delete "${doc.title}"? This removes all its chunks.`)) return;
    setError(null);
    try {
      await apiFetch(`/api/files/${doc.id}`, { method: "DELETE" });
      setNotice(`Deleted '${doc.title}'.`);
      // drop it from state instead of refetching — cheaper and no flicker
      setFiles((prev) => prev.filter((f) => f.id !== doc.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  const pools = user?.pools ?? [];

  return (
    <div className="flex min-h-full flex-1 flex-col bg-zinc-50 dark:bg-zinc-950">
      <Nav user={user} />
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
        <h1 className="text-2xl font-semibold tracking-tight">Files</h1>

        {/* upload form: file + pool + optional title */}
        <form
          onSubmit={upload}
          className="mt-4 flex flex-wrap items-end gap-3 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <label className="flex flex-col gap-1 text-sm">
            File
            <input ref={fileInput} type="file" required className="text-sm" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Pool
            <select
              value={uploadPool}
              onChange={(e) => setUploadPool(e.target.value)}
              className="rounded-md border border-zinc-300 bg-transparent px-2 py-1.5 outline-none transition-colors focus:border-brand focus:ring-2 focus:ring-brand/20 dark:border-zinc-700 dark:focus:border-red-400 dark:focus:ring-red-400/20"
            >
              {pools.map((pool) => (
                <option key={pool.id} value={pool.id}>
                  {pool.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Title <span className="text-zinc-400">(optional)</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
              className="rounded-md border border-zinc-300 bg-transparent px-2 py-1.5 outline-none transition-colors focus:border-brand focus:ring-2 focus:ring-brand/20 dark:border-zinc-700 dark:focus:border-red-400 dark:focus:ring-red-400/20"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-60 dark:focus-visible:outline-red-400"
          >
            {busy ? "Uploading…" : "Upload"}
          </button>
        </form>

        {/* result banners: green for success, red for the API's error message */}
        {notice && (
          <p className="mt-3 rounded-md border border-green-200 bg-green-50 px-3 py-2.5 text-sm text-green-800 dark:border-green-900 dark:bg-green-950/50 dark:text-green-300">
            {notice}
          </p>
        )}
        {error && (
          <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300">
            {error}
          </p>
        )}

        {/* list header: count + the pool filter */}
        <div className="mt-6 flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-600 dark:text-zinc-400">
            {files.length} file{files.length === 1 ? "" : "s"} you can see
          </h2>
          <select
            value={filterPool}
            onChange={(e) => changeFilter(e.target.value)}
            className="rounded-md border border-zinc-300 bg-transparent px-2 py-1 text-sm outline-none transition-colors focus:border-brand focus:ring-2 focus:ring-brand/20 dark:border-zinc-700 dark:focus:border-red-400 dark:focus:ring-red-400/20"
          >
            <option value="">All pools</option>
            {pools.map((pool) => (
              <option key={pool.id} value={pool.id}>
                {pool.name}
              </option>
            ))}
          </select>
        </div>

        {/* the file list — one row per document, with a delete button */}
        <ul className="mt-3 divide-y divide-zinc-200 overflow-hidden rounded-lg border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
          {files.map((doc) => (
            <li key={doc.id} className="flex items-center justify-between gap-4 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{doc.title}</p>
                <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                  {doc.filename} · {doc.fileType} · {formatSize(doc.size)} ·{" "}
                  {doc.chunkCount} chunks · {doc.poolIds.join(", ")} · by{" "}
                  {doc.uploadedBy} · {new Date(doc.createdAt).toLocaleString()}
                </p>
              </div>
              <button
                onClick={() => remove(doc)}
                className="shrink-0 rounded-md border border-red-300 px-3 py-1 text-xs text-red-700 transition-colors hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
              >
                Delete
              </button>
            </li>
          ))}
          {files.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-zinc-500">
              No files in this view yet.
            </li>
          )}
        </ul>
      </main>
    </div>
  );
}
