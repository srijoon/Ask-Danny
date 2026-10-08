"use client";

// The main chatbot interface. Each send goes to POST /api/ask; the backend does
// rewrite → access-filtered retrieval → rerank → LLM. conversationId keeps
// follow-up questions tied to the same thread.
import { Fragment, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { apiFetch, type AskResponse, type Source, type User } from "@/lib/api";
import { DEMO_USER, hasDemoSession } from "@/lib/demo-auth";
import { Nav } from "@/components/nav";

interface Message {
  role: "user" | "assistant";
  content: string;
  status?: string;
  sources?: Source[];
  searchQuery?: string;
}

// non-ok statuses get a labeled banner so it's obvious when the answer didn't
// come from documents (no_results) or the model was busy (rate_limited)
const STATUS_LABEL: Record<string, { label: string; className: string }> = {
  no_results: {
    label: "Nothing found",
    className: "bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
  },
  rate_limited: {
    label: "Busy",
    className: "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300",
  },
  error: {
    label: "Couldn't answer",
    className: "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300",
  },
};

// starting points for the empty state; clicking one fills the box
const EXAMPLE_QUESTIONS = [
  "How many vacation days do new hires get?",
  "What's the process for submitting event expenses?",
  "Who approves a new fundraising campaign?",
];

export default function AskPage() {
  const [user, setUser] = useState<User | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // drives the nav only — the 401 redirect lives in apiFetch, so a failed
    // /me call needs no handling here. the prototype account has no /me
    const me = hasDemoSession() ? Promise.resolve(DEMO_USER) : apiFetch<User>("/api/me");
    me.then(setUser).catch(() => {});
  }, []);

  useEffect(() => {
    // keep the newest message visible as the thread grows
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    // echo the question immediately so the UI feels instant while the backend
    // runs the (slow) retrieval + LLM pipeline
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    try {
      const res = await apiFetch<AskResponse>("/api/ask", {
        method: "POST",
        json: { question, conversationId },
      });
      // the backend creates the conversation lazily on first question; keeping
      // the id it returns makes every follow-up hit the same stored thread
      setConversationId(res.conversationId);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.answer.content,
          status: res.answer.status,
          sources: res.answer.sources,
          searchQuery: res.answer.searchQuery,
        },
      ]);
    } catch (err) {
      // errors render as an assistant message so the user sees them in context,
      // not as a dead page — the thread stays usable after a failure
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: err instanceof Error ? err.message : "Something went wrong.",
          status: "error",
        },
      ]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter adds a line break
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  function newChat() {
    setMessages([]);
    setConversationId(null);
    inputRef.current?.focus();
  }

  const empty = messages.length === 0 && !busy;

  return (
    <div className="flex h-dvh flex-col bg-zinc-50 dark:bg-zinc-950">
      <Nav user={user} />

      {/* message list scrolls; the composer stays pinned below it */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
          {empty ? (
            <div className="pt-10 sm:pt-16">
              <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                What do you want to know?
              </h1>
              <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
                Danny answers from the documents you have access to and shows where each answer
                came from.
              </p>
              <div className="mt-8 flex flex-col gap-2">
                {EXAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => {
                      setInput(q);
                      inputRef.current?.focus();
                    }}
                    className="rounded-lg border border-zinc-200 bg-white px-4 py-3 text-left text-sm text-zinc-700 transition-colors hover:border-brand/40 hover:bg-brand-tint/50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:border-red-900 dark:hover:bg-red-950/30"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between pb-4">
              <h1 className="text-sm font-medium text-zinc-500 dark:text-zinc-400">Conversation</h1>
              <button
                onClick={newChat}
                className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                New chat
              </button>
            </div>
          )}

          <ol className="space-y-6">
            {messages.map((msg, i) =>
              msg.role === "user" ? (
                <li key={i} className="flex justify-end">
                  <p className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[15px] whitespace-pre-wrap text-white">
                    {msg.content}
                  </p>
                </li>
              ) : (
                <li key={i} className="flex gap-3">
                  <DannyAvatar />
                  <Answer message={msg} />
                </li>
              ),
            )}
            {busy && (
              <li className="flex gap-3" aria-live="polite">
                <DannyAvatar />
                <p className="flex items-center gap-2 pt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
                  <span className="flex gap-1" aria-hidden>
                    <Dot delay="0ms" />
                    <Dot delay="150ms" />
                    <Dot delay="300ms" />
                  </span>
                  Searching your documents…
                </p>
              </li>
            )}
          </ol>
          <div ref={bottomRef} />
        </div>
      </div>

      {/* composer */}
      <div className="border-t border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <form onSubmit={send} className="mx-auto flex w-full max-w-3xl items-end gap-2 px-4 py-3 sm:px-6">
          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <textarea
            id="question"
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask Danny a question…"
            rows={1}
            maxLength={2000}
            disabled={busy}
            className="max-h-40 min-h-11 flex-1 resize-none rounded-xl border border-zinc-300 bg-white px-4 py-2.5 text-[15px] text-zinc-900 outline-none field-sizing-content placeholder:text-zinc-400 focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50 dark:focus:border-red-400 dark:focus:ring-red-400/20"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="h-11 rounded-xl bg-brand px-5 text-sm font-medium text-white transition-colors hover:bg-brand-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-40"
          >
            Send
          </button>
        </form>
        <p className="mx-auto max-w-3xl px-4 pb-3 text-xs text-zinc-400 sm:px-6 dark:text-zinc-500">
          Enter to send, Shift + Enter for a new line. Check important answers against the source.
        </p>
      </div>
    </div>
  );
}

function DannyAvatar() {
  return (
    <span
      aria-hidden
      className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand text-sm font-bold text-white"
    >
      D
    </span>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="size-1.5 animate-bounce rounded-full bg-brand motion-reduce:animate-none"
      style={{ animationDelay: delay }}
    />
  );
}

function Answer({ message }: { message: Message }) {
  const status = message.status && message.status !== "ok" ? STATUS_LABEL[message.status] : null;
  const sources = message.sources ?? [];

  return (
    <div className="min-w-0 flex-1 space-y-3">
      <div className="rounded-2xl rounded-tl-md border border-zinc-200 bg-white px-4 py-3 text-[15px] leading-relaxed text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
        {status && (
          <span
            className={`mb-2 inline-block rounded px-1.5 py-0.5 text-xs font-medium ${status.className}`}
          >
            {status.label}
          </span>
        )}
        <p className="whitespace-pre-wrap">
          <WithCitations text={message.content} />
        </p>
      </div>

      {/* the rewritten query the backend actually searched with */}
      {message.searchQuery && (
        <p className="px-1 text-xs text-zinc-400 dark:text-zinc-500">
          Searched for: {message.searchQuery}
        </p>
      )}

      {/* citations: one expandable entry per retrieved excerpt */}
      {sources.length > 0 && (
        <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <p className="border-b border-zinc-200 px-4 py-2 text-xs font-medium text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            Sources
          </p>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {sources.map((source) => (
              <li key={source.n}>
                <details className="group px-4 py-2.5 text-sm">
                  <summary className="flex cursor-pointer list-none items-center gap-3 text-zinc-700 dark:text-zinc-300">
                    <CiteBadge n={source.n} />
                    <span className="min-w-0 flex-1 truncate">
                      {source.title}
                      {source.page ? (
                        <span className="text-zinc-400"> · page {source.page}</span>
                      ) : null}
                    </span>
                    <span
                      aria-hidden
                      className="text-zinc-400 transition-transform group-open:rotate-90"
                    >
                      ›
                    </span>
                  </summary>
                  <p className="mt-2 ml-9 border-l-2 border-brand/30 pl-3 text-[13px] leading-relaxed whitespace-pre-wrap text-zinc-600 dark:text-zinc-400">
                    {source.text}
                  </p>
                </details>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// turns "[1]" and "[2][3]" in an answer into small red source markers
function WithCitations({ text }: { text: string }) {
  const parts = text.split(/(\[\d{1,2}\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d{1,2})\]$/);
        return match ? (
          <CiteBadge key={i} n={Number(match[1])} inline />
        ) : (
          <Fragment key={i}>{part}</Fragment>
        );
      })}
    </>
  );
}

function CiteBadge({ n, inline = false }: { n: number; inline?: boolean }) {
  return (
    <span
      className={`inline-grid place-items-center rounded bg-brand-tint font-semibold text-brand dark:bg-red-950/60 dark:text-red-300 ${
        inline ? "mx-0.5 h-[1.15rem] min-w-[1.15rem] px-1 align-[0.1em] text-[0.7rem]" : "size-6 shrink-0 text-xs"
      }`}
    >
      {n}
    </span>
  );
}
