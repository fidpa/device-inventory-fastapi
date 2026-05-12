# Architecture

A bird's-eye view of how the components fit together.

## Components

```
┌──────────────────────────┐         ┌──────────────────────────┐
│  Windows / macOS / Linux │         │  Networked Printers      │
│  end-user clients        │         │  (SNMP)                  │
└────────────┬─────────────┘         └────────────┬─────────────┘
             │ collect-sysinfo.{ps1,py}           │ collect-printers.ps1
             │ writes JSON                        │ writes JSON
             ▼                                    ▼
┌──────────────────────────────────────────────────────────────┐
│  WebDAV server (Nextcloud / ownCloud / Seafile)              │
│  /sysinfo/inbox/<files>.json                                 │
└──────────────────────────┬───────────────────────────────────┘
                           │ scripts/import_sysinfo.py
                           │ scripts/import_printers.py
                           │ (systemd timer: hourly / daily)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI (src/app.py) — single-file web app                  │
│  ├─ AuthMiddleware (HMAC cookie verify)                      │
│  ├─ SecurityHeadersMiddleware (CSP, X-Frame-Options, …)      │
│  ├─ Routes (35+) — login, devices, printers, CTR, services   │
│  ├─ Jinja2 templates (12 HTML files)                         │
│  ├─ PDF builders (fpdf2)                                     │
│  └─ SQLite (WAL, foreign keys)                               │
└──────────────────────────┬───────────────────────────────────┘
                           │ uvicorn 127.0.0.1:8004
                           ▼
                    nginx reverse proxy
                           │ HTTPS
                           ▼
                       Browser
```

## Data flow

1. **Collection (client side)**: An end user runs the platform-specific collector. The script queries hardware/software via OS-native APIs (CIM on Windows, `system_profiler` on macOS, `lshw` / `dmidecode` on Linux) and writes a JSON file with a stable schema.

2. **Upload (client → cloud)**: The collector uploads the JSON via HTTP `PUT` to a WebDAV endpoint. On failure it falls back to writing the file to the user's Desktop, so the user can email it to an admin.

3. **Import (server side)**: A systemd timer runs `scripts/import_sysinfo.py` periodically. The script lists the inbox via `PROPFIND`, downloads new files, parses JSON, and inserts/updates rows in the SQLite `devices` table.

4. **Web UI**: The operator logs in (bcrypt + HMAC cookie). Routes render Jinja2 templates that query SQLite via the synchronous `sqlite3` module.

5. **Exports**: PDF reports are rendered server-side with `fpdf2`; CSVs use the stdlib `csv` module. Both stream the output back to the browser as `attachment`.

## Process model

- **Single uvicorn worker** by default. Concurrency is handled by FastAPI's async event loop; SQLite WAL mode allows concurrent reads while one write is in progress.
- **systemd timers** run import scripts as `Type=oneshot` services. They exit cleanly after each import — no long-running daemon.
- **No background workers** (no Celery, no RQ, no message queue). Heavy operations (PDF generation, CSV export) happen synchronously on the request thread; for the data volumes this app targets (< 200 devices) that's fast enough.

## Storage

- **SQLite** (`db/devices.db`) — WAL mode, foreign keys enabled, ~10 tables.
- **WebDAV inbox** — source of truth for raw collected data. Acts as a queue: files stay until manually deleted.
- **No Redis, no PostgreSQL, no message broker.**

## Security boundaries

| Boundary | Mechanism |
|----------|-----------|
| Internet ↔ nginx | TLS (Let's Encrypt) |
| nginx ↔ uvicorn | Loopback only (`127.0.0.1:8004`) |
| Browser ↔ FastAPI | HMAC-signed session cookie (HttpOnly, Secure, SameSite=Lax) |
| Login attempts | Per-IP rate limit (5 attempts / 60 s) |
| User input → SQL | Parameterized queries (no string interpolation with user data) |
| Output → browser | CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy |
| FastAPI ↔ filesystem | App runs as the dedicated `device-inventory` system user with no shell |
| FastAPI ↔ WebDAV | Outbound only; credentials read from `.env` (mode 0600) |

## Why this architecture

See [`docs/explanation/why-fastapi-monolith.md`](../explanation/why-fastapi-monolith.md) for the design rationale.
