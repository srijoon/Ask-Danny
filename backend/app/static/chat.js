(function () {
  "use strict";

  const state = { conversationId: window.CHAT.conversationId, busy: false, count: 0 };
  const messagesEl = document.getElementById("messages");
  const welcomeEl = document.getElementById("welcome");
  const form = document.getElementById("composer");
  const input = document.getElementById("question");
  const sendBtn = document.getElementById("send");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function inline(text, msgId) {
    return escapeHtml(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[(\d{1,2})\]/g, `<a class="cite" href="#src-${msgId}-$1">$1</a>`);
  }

  function renderMarkdown(text, msgId) {
    const out = [];
    let list = null;
    const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    for (const block of text.split(/\n{2,}/)) {
      for (const line of block.split("\n")) {
        const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
        const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
        const heading = line.match(/^#{1,4}\s+(.*)$/);
        if (bullet || numbered) {
          const tag = bullet ? "ul" : "ol";
          if (list !== tag) { closeList(); out.push(`<${tag}>`); list = tag; }
          out.push(`<li>${inline((bullet || numbered)[1], msgId)}</li>`);
        } else if (heading) {
          closeList();
          out.push(`<p><strong>${inline(heading[1], msgId)}</strong></p>`);
        } else if (line.trim()) {
          closeList();
          out.push(`<p>${inline(line, msgId)}</p>`);
        }
      }
      closeList();
    }
    return out.join("");
  }

  function renderSources(sources, msgId) {
    if (!sources || !sources.length) return "";
    const items = sources.map((s) => {
      const page = s.page ? ` · p. ${s.page}` : "";
      return `<details class="source" id="src-${msgId}-${s.n}">
        <summary><span class="badge">${s.n}</span> ${escapeHtml(s.title)}${page}</summary>
        <div class="source-text">${escapeHtml(s.text)}</div>
      </details>`;
    });
    return `<div class="sources"><div class="muted small">Sources</div>${items.join("")}</div>`;
  }

  function addMessage(message, question) {
    welcomeEl.hidden = true;
    const msgId = ++state.count;
    const el = document.createElement("div");
    el.className = `message ${message.role}`;
    if (message.role === "user") {
      el.innerHTML = `<div class="bubble">${escapeHtml(message.content)}</div>`;
    } else {
      const status = message.status || "ok";
      const rewritten = message.search_query && question && message.search_query !== question
        ? `<div class="muted small">Searched for: “${escapeHtml(message.search_query)}”</div>` : "";
      const intro = status === "rate_limited" || status === "error"
        ? (message.sources && message.sources.length ? `<p class="muted small">These documents look relevant:</p>` : "")
        : "";
      el.innerHTML = `<div class="bubble status-${status}">
        ${status === "ok" ? renderMarkdown(message.content, msgId) : `<p>${escapeHtml(message.content)}</p>`}
        ${rewritten}${intro}${renderSources(message.sources, msgId)}
      </div>`;
    }
    messagesEl.appendChild(el);
    el.scrollIntoView({ block: "end", behavior: "smooth" });
    return el;
  }

  function addPending() {
    const el = document.createElement("div");
    el.className = "message assistant";
    el.innerHTML = `<div class="bubble pending"><span class="dots"><i></i><i></i><i></i></span> Searching your documents…</div>`;
    messagesEl.appendChild(el);
    el.scrollIntoView({ block: "end", behavior: "smooth" });
    return el;
  }

  function addToSidebar(id, title) {
    const list = document.getElementById("conversation-list");
    list.querySelector(".empty")?.remove();
    list.querySelectorAll("li.active").forEach((li) => li.classList.remove("active"));
    const li = document.createElement("li");
    li.className = "active";
    const a = document.createElement("a");
    a.href = `/?c=${encodeURIComponent(id)}`;
    a.textContent = a.title = title;
    li.appendChild(a);
    list.prepend(li);
  }

  async function ask(question) {
    state.busy = true;
    sendBtn.disabled = true;
    addMessage({ role: "user", content: question });
    const pending = addPending();
    try {
      const res = await fetch(window.CHAT.askUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ question, conversation_id: state.conversationId }),
      });
      let data = {};
      try { data = await res.json(); } catch (_) { }
      pending.remove();
      if (!res.ok) {
        addMessage({ role: "assistant", status: "error",
                     content: data.error || `Something went wrong (HTTP ${res.status}). Please try again.` });
        return;
      }
      if (!state.conversationId) {
        state.conversationId = data.conversation_id;
        history.replaceState(null, "", `/?c=${encodeURIComponent(data.conversation_id)}`);
        addToSidebar(data.conversation_id, data.title);
      }
      addMessage({ role: "assistant", ...data.answer }, question);
    } catch (err) {
      pending.remove();
      addMessage({ role: "assistant", status: "error", content: "Couldn't reach the server. Check your connection and try again." });
    } finally {
      state.busy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question || state.busy) return;
    input.value = "";
    input.style.height = "";
    ask(question);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  input.addEventListener("input", () => {
    input.style.height = "";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  });

  let lastQuestion = null;
  for (const message of window.CHAT.messages) {
    addMessage(message, lastQuestion);
    if (message.role === "user") lastQuestion = message.content;
  }
  input.focus();
})();
