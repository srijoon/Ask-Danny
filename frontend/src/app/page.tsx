import { BackendStatus } from "./backend-status";

export default function Home() {
  return (
    <div className="flex flex-col flex-1 items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex w-full max-w-3xl flex-col gap-6 py-32 px-16 bg-white dark:bg-black">
        <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Next.js + Flask
        </h1>
        <p className="text-lg leading-8 text-zinc-600 dark:text-zinc-400">
          Frontend lives in <code className="font-mono">frontend/</code>, backend in{" "}
          <code className="font-mono">backend/</code>. Requests to{" "}
          <code className="font-mono">/api/*</code> are proxied to Flask.
        </p>
        <BackendStatus />
      </main>
    </div>
  );
}
