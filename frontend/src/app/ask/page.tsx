"use client";

// The main chatbot interface. Each send goes to POST /api/ask; the backend does
// rewrite → access-filtered retrieval → rerank → LLM. conversationId keeps
// follow-up questions tied to the same thread.
import { useEffect, useRef, useState, type FormEvent } from "react";

import { apiFetch, type AskResponse, type Source, type User } from "@/lib/api";
import { Nav } from "@/components/nav";

interface Message {
  role: "user" | "assistant";
  content: string;
  status?: string;
  sources?: Source[];
  searchQuery?: string;
}

// non-ok statuses get a colored label so it's obvious when the answer didn't
// come from documents (no_results) or the model was busy (rate_limited)
const STATUS_STYLE: Record<string, string> = {
  no_results: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  rate_limited: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  error: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export default function AskPage() {
  const [user, setUser] = useState<User | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // drives the nav only — the 401 redirect lives in apiFetch, so a failed
    // /me call needs no handling here
    apiFetch<User>("/api/me").then(setUser).catch(() => {});
  }, []);

  useEffect(() => {
    // keep the newest message visible as the thread grows
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(e: FormEvent) {
    e.preventDefault();
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
      // errors render as an assistant bubble so the user sees them in context,
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
    }
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <Nav user={user} />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pb-4">
        {/* header: title + "New chat" once a conversation exists */}
        <div className="flex items-center justify-between py-3">
          <h1 className="text-lg font-semibold">Ask</h1>
          {conversationId && (
            <button
              onClick={() => {
                setMessages([]);
                setConversationId(null);
              }}
              className="rounded border border-zinc-300 px-3 py-1 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              New chat
            </button>
          )}
        </div>

        {/* message list */}
        <div className="flex-1 space-y-4 overflow-y-auto py-2">
          {messages.length === 0 && !busy && (
            // empty state, before the first question
            <p className="mt-16 text-center text-sm text-zinc-500 dark:text-zinc-400">
              Ask a question about the documents you have access to.
            </p>
          )}
          {messages.map((msg, i) =>
            // user bubbles on the right, assistant answers on the left
            msg.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl bg-black px-4 py-2 text-sm whitespace-pre-wrap text-white dark:bg-zinc-50 dark:text-black">
                  {msg.content}
                </div>
              </div>
            ) : (
              <div key={i} className="flex justify-start">
                <div className="max-w-[80%] space-y-2">
                  {/* the answer bubble; non-"ok" statuses get a colored badge */}
                  <div className="rounded-2xl border border-zinc-200 px-4 py-2 text-sm whitespace-pre-wrap dark:border-zinc-800">
                    {msg.status && msg.status !== "ok" && (
                      <span
                        className={`mr-2 inline-block rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_STYLE[msg.status] ?? ""}`}
                      >
                        {msg.status.replace("_", " ")}
                      </span>
                    )}
                    {msg.content}
                  </div>
                  {/* the rewritten query the backend actually searched with */}
                  {msg.searchQuery && msg.searchQuery !== "" && (
                    <p className="px-1 text-xs text-zinc-400">
                      searched: {msg.searchQuery}
                    </p>
                  )}
                  {/* citations: one collapsible card per retrieved chunk */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="space-y-1">
                      {msg.sources.map((source) => (
                        <details
                          key={source.n}
                          className="rounded border border-zinc-200 px-3 py-1.5 text-xs dark:border-zinc-800"
                        >
                          <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">
                            [{source.n}] {source.title}
                            {source.page ? `, page ${source.page}` : ""}
                            <span className="text-zinc-400">
                              {" "}
                              · score {source.score.toFixed(3)}
                            </span>
                          </summary>
                          <p className="mt-1 whitespace-pre-wrap text-zinc-500">
                            {source.text}
                          </p>
                        </details>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ),
          )}
          {/* pending indicator while the backend pipeline runs */}
          {busy && (
            <div className="flex justify-start">
              <div className="rounded-2xl border border-zinc-200 px-4 py-2 text-sm text-zinc-500 dark:border-zinc-800">
                Thinking…
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* input bar pinned to the bottom */}
        <form onSubmit={send} className="flex gap-2 pt-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question…"
            maxLength={2000}
            disabled={busy}
            className="flex-1 rounded-full border border-zinc-300 bg-transparent px-4 py-2 text-sm dark:border-zinc-700"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-full bg-black px-5 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40 dark:bg-zinc-50 dark:text-black dark:hover:bg-zinc-200"
          >
            Send
          </button>
        </form>
      </main>
    </div>
  );
}
