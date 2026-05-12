# Why a Single-File FastAPI Monolith

A look at the architectural choices behind this project — and why they're not arbitrary.

## The core decision: one Python file (~2,000 LOC)

`src/app.py` contains everything: routes, middleware, database setup, PDF builders, helper functions. There are no `routes/`, `models/`, `services/` directories.

### Why this is a feature, not a bug

For a project of this scope, splitting a 2,000-line file into 15 small modules **adds complexity without removing any**. You still need to read the same logic to understand how the app works; you just have to navigate more files to find it.

The DIATAXIS guideline that drove this layout: optimize for the typical reader, not the edge case. The typical reader of this code is one of:

- A solo developer maintaining their own deployment.
- An open-source contributor making a small PR.
- A future-you debugging an issue at 22:00 on a Friday.

For all three, "open `app.py`, ⌘F for the route or table name" is faster than "find the right module in the right subdirectory". The file is large, but it's flat and grep-able.

### When this stops being a good idea

Around 3,000+ LOC the trade-off flips. If you find yourself adding multi-page features (like multi-tenant support, fine-grained permissions, async background processing), it's time to split. Suggested split:

```
src/
├── app.py              # FastAPI app instance + middleware wiring
├── config.py           # Env vars, paths, constants
├── db.py               # SQLite helpers (get_db, ensure_db)
├── auth.py             # Token, bcrypt, rate limiting
├── routes/
│   ├── devices.py
│   ├── printers.py
│   ├── ctr.py
│   └── services.py
├── exporters/
│   ├── pdf.py
│   └── csv.py
└── webdav.py
```

Until you hit that point, the single file wins.

## SQLite, not PostgreSQL

The application is single-server. There's no horizontal scaling story, no read replicas, no cross-region replication. SQLite handles up to ~100k rows with sub-millisecond query latency on modern SSDs — that covers the target audience (50–200 devices, hundreds of printer scans, dozens of services) by orders of magnitude.

What you give up:

- **Concurrent writes**: WAL mode enables one writer + many readers, but two simultaneous writers will block. For this app's write rate (one import every 1–24 h) that's a non-issue.
- **Network access**: SQLite is a file-on-disk. You cannot run uvicorn on host A and the database on host B. If your deployment requires that, switch to PostgreSQL.
- **Online schema migrations**: there's no Alembic or Django Migrations. New columns go directly into `ensure_db()` with `ALTER TABLE ... ADD COLUMN`.

What you gain:

- Zero-dependency deployment: `apt install python3-pip` and you're done.
- Trivial backups: copy a single file.
- No connection pooling, no port management, no `pg_hba.conf`.

## No frontend build step

The UI is server-rendered Jinja2 + vanilla JavaScript. No npm, no webpack, no React.

The reasoning is the same as the monolith decision: **build pipelines are a maintenance tax**. They break across Node.js versions, they pull in hundreds of transitive dependencies, they require a separate `npm audit` cycle, and they slow the dev loop (changes need a rebuild). For a CRUD app with maybe 10 pages of UI, none of the React / Vue / Svelte ecosystems pay for themselves.

What you give up:

- Reactive client-side state (good for high-frequency updates).
- Component reuse libraries (the project re-implements modal dialogs, toasts, table sorting in vanilla JS — a few hundred lines).
- TypeScript type safety on the client.

What you gain:

- Works without a build step. You can edit `static/js/device.js` and refresh the browser.
- One language (Python) for everything except DOM manipulation.
- Tiny page weight (~20 KB CSS + 5 KB JS, no React runtime).

## Synchronous SQLite, async FastAPI

FastAPI is async, but the database calls are synchronous (`sqlite3.connect()`). This is on purpose:

- Each request opens a connection, runs queries, and closes it — typical query takes < 1 ms.
- Wrapping `sqlite3` in `aiosqlite` would add overhead without benefit at this scale.
- Multiple concurrent requests still proceed in parallel because FastAPI runs sync route handlers in a thread pool.

For higher concurrency or genuinely slow queries, switch to `asyncpg` + PostgreSQL. Until then, KISS wins.

## No background workers

Long-running operations (PDF generation, CSV export, WebDAV import) all run synchronously on the request thread. There's no Celery, no RQ, no Redis-backed job queue.

This works because:

- PDF generation for 200 devices completes in < 1 s.
- Import scripts run on systemd timers, not request threads.
- Users tolerate a 1–2 s spinner on rare export operations.

If exports start exceeding 5–10 s, the right next step is **caching** (precompute the PDF on import, serve a cached copy), not a worker queue. Workers add deployment complexity (a second daemon to monitor, a queue to administer) that's hard to justify at this scale.

## Summary

Every choice in this stack is biased toward **lowest possible operational complexity** for a well-defined user base (one organization, < 200 devices, one operator). Anywhere you see "this would be nicer with X", X is almost always more complexity, more dependencies, more things that can break at 03:00 when you're paged.

If your workload outgrows these constraints, this codebase is small enough that you can fork it, add what you need, and move on. The architecture is meant to be **disposable, not eternal** — which is itself a deliberate design principle.
