// The Ask Danny name with its square "D" mark. "dark" is for the red sign-in
// panel (white mark, white text); "light" is for white pages (red mark).
export function Wordmark({ tone = "dark" }: { tone?: "dark" | "light" }) {
  const onRed = tone === "dark";
  return (
    <span className="inline-flex items-center gap-2.5">
      <span
        aria-hidden
        className={`grid size-8 place-items-center rounded-lg text-base font-bold ${
          onRed ? "bg-white text-brand-deep" : "bg-brand text-white"
        }`}
      >
        D
      </span>
      <span
        className={`text-lg font-semibold tracking-tight ${
          onRed ? "text-white" : "text-zinc-900 dark:text-zinc-50"
        }`}
      >
        Ask Danny
      </span>
    </span>
  );
}
