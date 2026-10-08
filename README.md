# Ask-Danny

Ask questions about internal documents and get cited answers, limited to what each user is allowed to see. It runs on a $0 budget: local embedding and rerank models, MongoDB Atlas free tier (M0), and a free OpenRouter model or a local Ollama model.

```
.
├── backend/                 Flask app (Blueprints + Jinja UI): the RAG MVP
│   ├── app/
│   │   ├── auth/            login, users, login_required / admin_required
│   │   ├── admin/           document upload + access, user management
│   │   ├── chat/            chat UI, conversations, per-question answer flow
│   │   ├── ingestion/       parsers (PDF/DOCX/TXT/MD/CSV), chunker, ingest service
│   │   ├── retrieval/       embeddings, $vectorSearch + $search, RRF, reranker, pipeline
│   │   ├── generation/      llm.py (OpenRouter / Ollama behind one interface), prompts
│   │   ├── permissions.py   access model
│   │   ├── routes.py        JSON API (/api/*): session auth, files, admin
│   │   ├── db.py            collections + Atlas index definitions
│   │   └── cli.py           flask init-db / create-user / ingest / ask
│   └── tests/
├── frontend/                Next.js scaffold (not used by the RAG UI; see below)
└── package.json             root scripts
```

## Setup

Prerequisites: Python 3.11+ and a free MongoDB Atlas M0 cluster. Node 20+ is only needed for the root npm scripts and the Next.js scaffold.

```bash
npm run setup                      # or: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Create `backend/.env` with the three required settings. Everything else has a default in `backend/app/config.py`.

```
MONGODB_URI=<your-atlas-uri>
OPENROUTER_API_KEY=<your-openrouter-key>
FLASK_SECRET_KEY=<long-random-string>
```

On Linux servers, install the CPU-only PyTorch wheel first to skip ~2 GB of CUDA libraries: `pip install torch --index-url https://download.pytorch.org/whl/cpu`.

The first start downloads the models from Hugging Face: about 130 MB for `bge-small-en-v1.5` and 1.1 GB for `bge-reranker-base`. After that they load from the local cache.

```bash
cd backend
source .venv/bin/activate                  # once per terminal; a global `flask` lacks these deps
flask init-db                              # collections, indexes, both Atlas Search indexes
flask create-user admin --admin --groups hr   # prompts for a password
flask run                                  # http://127.0.0.1:8000
```

Then sign in, upload documents under **Documents**, choose which groups can see each one, and add users under **Users**.

Other commands:

```bash
flask ingest docs/*.pdf --groups hr,finance     # bulk ingest (or --everyone)
flask ask "How many vacation days do new hires get?" --user alice
```

`npm run dev` starts both the Next.js frontend (:3000) and Flask (:8000). The Next.js app at :3000 is the simple API client: `/login`, `/ask` (chatbot), `/files` (pool-scoped upload/list/delete) and `/admin` (usage, users, groups). The Jinja app on :8000 is still there with its own chat and admin pages.

## How a question is answered

1. **Query rewrite.** This runs only when the conversation has history and `QUERY_REWRITE_ENABLED=true`. The LLM turns the follow-up into a standalone search query. If the rewrite fails, the original question is used.
2. **Hybrid search, with the permission filter inside both stages:**
   - `$vectorSearch` with `numCandidates` 200 and `limit` 30
   - Atlas Search `$search` (`text` on `text` and `title`) with `limit` 30
   - The two result lists are merged with Reciprocal Rank Fusion (k = 60).
3. **Local rerank.** `BAAI/bge-reranker-base` scores the top 20 merged chunks, and the top 6 are kept.
4. **Threshold.** Chunks scoring below `RERANK_MIN_SCORE` (default 0.1, on a 0–1 sigmoid scale) are dropped. If none are left, the user is told nothing relevant was found in the documents they can access, and **no LLM call is made**.
5. **One LLM call** writes the answer from the numbered excerpts, citing them as [1], [2], and so on. The UI shows the sources, and each one expands to the cited text.

LLM budget per question:

| Situation | LLM calls |
| --- | --- |
| First question in a chat | 1 |
| Follow-up question (rewrite on) | 2 |
| `QUERY_REWRITE_ENABLED=false` | always 1 at most |
| Nothing relevant found | 0 for the answer |
| Ingestion | never |

If the rewrite call is rate-limited, the answer call is skipped rather than spending another request.

**Embeddings.** `BAAI/bge-small-en-v1.5` has 384 dimensions and runs on CPU. Vectors are normalized and compared by cosine similarity.
- As the model card recommends, queries get the prefix `Represent this sentence for searching relevant passages: ` and passages get none.
- Vectors are stored as BSON `float32` BinData, about a third of the size of a BSON array of doubles, which helps under the 512 MB limit.
- Both models load once per process at startup. Other `flask` commands and the debug reloader's watcher process skip loading them.

## Access control

Every document and every one of its chunks stores `access`, a list of principals such as `["group:hr", "user:admin"]` or `["everyone"]`. A user's principals are:
- `everyone`
- `user:<username>`
- `group:<g>` for each of their groups

The Atlas queries return only chunks whose `access` shares at least one principal with the user's. Results are filtered again in Python as a safeguard. Changing a document's access updates its chunks, and Atlas indexes the change within seconds.

Admins manage users and can upload to any groups from the **Documents** page. Members upload to and delete from their own pools through the JSON API below.

## JSON API

Everything under `/api` speaks JSON, including errors (`{"error": "..."}`). It uses the same session cookie and CSRF protection as the web UI:

1. `GET /api/csrf` returns `{"csrfToken": ...}`.
2. `POST /api/login` with `{"username", "password"}` and the header `X-CSRF-Token: <token>`. The response carries the user and a **new** `csrfToken`.
3. Send that token as `X-CSRF-Token` on every later `POST` / `DELETE`.

**Pools.** A pool is `shared` (every signed-in user) or `group:<name>` (members of that group). A user's pools are `shared` plus one per group.

| Endpoint | Who | What |
| --- | --- | --- |
| `GET /api/me` | signed in | user, groups and pools |
| `POST /api/ask` | signed in | `{"question", "conversationId"?}` → answer with `status`, cited `sources`, the `searchQuery` actually used, and the `conversationId` to keep threading follow-ups |
| `POST /api/logout` | anyone | clears the session |
| `GET /api/files?poolId=` | signed in | documents you can see, newest first; `poolId` narrows to one of your pools |
| `GET /api/files/:id` | can see it | one document's metadata |
| `POST /api/files` | pool member | multipart `file` + `poolId`, optional `title` (≤ 200 chars) |
| `DELETE /api/files/:id` | can see it | removes the document and its chunks |
| `GET /api/admin/users` | admin | users and their groups |
| `GET /api/admin/groups` | admin | every group with members and document counts |
| `GET /api/admin/usage` | admin | documents, chunks, questions by status and user, answer calls skipped |

Admins can list, read and delete any document and upload to any valid pool. Documents you can't see return 404, the same as missing ones.

Upload responses:
- `201` with the new document.
- `400` for a missing file or bad `poolId`/title.
- `403` for a pool you're not in.
- `409` for a byte-identical file that already exists. `fileId` is only set when you can see the existing document.
- `413` when the request is over `MAX_UPLOAD_MB`.
- `415` for an unsupported type.
- `422` when no text could be read, or the file needs more than `MAX_CHUNKS_PER_DOCUMENT` chunks (default 500).
- `503` when the database is unreachable.

CSV files are indexed one row per paragraph, as `Header: value; Header: value`. DOCX files that decompress past 50 MB are rejected before parsing.

## MongoDB Atlas free tier (M0)

Limits that matter here, from the [Atlas Search limitations](https://www.mongodb.com/docs/atlas/atlas-search/limitations/) and [free cluster limits](https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/) docs:
- **3 search indexes in total**, counting vector and text indexes together. This app uses 2: `chunks_vector` and `chunks_text`. **Full-text Atlas Search is available on M0, so hybrid search fits.**
- Each index definition can be at most 3 KB. Ours are well under that.
- 512 MB of storage.
- 100 operations per second.
- MongoDB 8.0, so RRF is done in Python rather than with `$rankFusion`.

`flask init-db` creates both search indexes through the driver. If your cluster refuses that, it prints the JSON definitions so you can paste them into the Atlas UI JSON editor on the `chunks` collection. The **Documents** page shows each index's status and whether search is running in hybrid or vector-only mode.

If keyword search is unavailable, the app falls back to vector-only search:
- **Automatic:** a failing `$search` query is logged and that question uses vector search only.
- **Manual:** set `KEYWORD_SEARCH_ENABLED=false` to turn keyword search off.

For local development without Atlas, run `docker run -p 27017:27017 mongodb/mongodb-atlas-local:8.0` and set `MONGODB_URI=mongodb://localhost:27017/?directConnection=true`. This image supports `$vectorSearch` and `$search`.

## LLM providers

Set `LLM_PROVIDER` in `.env`. Nothing else in the code changes.

**`openrouter` (default)**
- Default model: `CHAT_MODEL=google/gemma-4-31b-it:free`. This dense 31B instruct model was the strongest general-purpose option on OpenRouter's free list as of 2026-10-07. Most of the other free models are coding agents, tiny models, or reasoning-first models. Gemma's reasoning mode is off by default, so its answers are fast and don't use up the token budget.
- Free keys allow 20 requests per minute and 50 per day. The daily limit rises to 1,000 once the account has ever bought $10 of credits.
- HTTP 429 responses become a friendly message in the chat. Daily-limit messages include the reset time, and the matched sources are still shown.
- `OPENROUTER_FALLBACK_MODELS` can list more `:free` models. OpenRouter tries them inside the same single request.
- If you get a 404 for a free model, check the OpenRouter privacy settings for free endpoints.

**`ollama`**
- Install the model and start the server: `ollama pull llama3.1:8b` (or `qwen2.5:7b`), then `ollama serve`.
- Set `OLLAMA_URL` and `OLLAMA_MODEL`.

## Tests

```bash
npm test        # or: cd backend && .venv/bin/pytest
```

The unit tests use mongomock, fake models and mocked HTTP, so they need no network access or downloads.
