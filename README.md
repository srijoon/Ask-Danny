# Ask-Danny

Monorepo with a **Next.js** frontend and a **Flask** backend.

```
.
├── frontend/          Next.js 16 (App Router, TypeScript, Tailwind)
├── backend/           Flask 3 API
│   ├── app/           application package (create_app factory, routes)
│   └── tests/         pytest suite
└── package.json       root scripts + npm workspace
```

## Prerequisites

- Node.js 20+
- Python 3.10+

## Setup

```bash
npm run setup        # npm install + create backend/.venv and install Python deps
```

Optional: copy `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env.local`.

## Development

```bash
npm run dev          # runs both servers
```

- Frontend: http://localhost:3000
- Backend:  http://127.0.0.1:8000

The Next.js dev server proxies `/api/*` to Flask (see `frontend/next.config.ts`), so frontend code just calls `fetch("/api/...")` and no CORS setup is needed. Set `BACKEND_URL` to point the proxy elsewhere.

Run one side only with `npm run dev:frontend` or `npm run dev:backend`.

## Other scripts

| Command         | What it does                     |
| --------------- | -------------------------------- |
| `npm test`      | Run backend tests (pytest)       |
| `npm run lint`  | Lint the frontend                |
| `npm run build` | Production build of the frontend |

## Adding API routes

Add endpoints to `backend/app/routes.py` (the `api` blueprint is mounted at `/api`), or register new blueprints in `backend/app/__init__.py`.
