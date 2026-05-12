# Device Inventory — FastAPI-based IT asset tracking without agents

![CI](https://github.com/fidpa/device-inventory-fastapi/actions/workflows/lint.yml/badge.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009485.svg)
![Status](https://img.shields.io/badge/Status-Production-success.svg)

A FastAPI-based device inventory management system with cross-platform sysinfo collection (Windows, macOS, Linux), WebDAV-based data sync, SNMP printer discovery, and PDF/CSV exports — built as a single-file deployment that runs on a small VPS.

## The Problem

Most small organizations track their IT inventory in spreadsheets that drift out of sync within weeks. Hardware specs go stale the moment someone upgrades a laptop. Asset numbers live in one Excel sheet, VPN assignments in another, and printer toner status nowhere at all. By the time you need the data — for an audit, a budget round, an end-of-life rollout — the spreadsheet is half wrong and nobody knows which version is current.

The off-the-shelf alternatives (Snipe-IT, GLPI, OCS Inventory) are heavyweight: PHP + MySQL + Redis stacks, agent-based collection, multi-tenant overhead, and configuration surfaces measured in screens, not minutes. For an organization with 50–200 devices, that's overkill — but Excel is also clearly not enough.

This project is the middle ground: a single Python file (~2k LOC) backed by SQLite, with simple "double-click to collect" tools for end users and a one-shot WebDAV sync that requires no agents on the clients.

## Features

- ✅ **Cross-platform device collection**: Windows (PowerShell + CIM), macOS (Python + `system_profiler`), Linux (Python + `lshw`/`dmidecode`)
- ✅ **End-user friendly**: double-click `.bat` / `.command` — no admin rights required on the client
- ✅ **WebDAV-based sync**: works with any WebDAV server (Nextcloud, ownCloud, Seafile)
- ✅ **SNMP printer discovery**: auto-detects networked printers, captures toner levels, page counts, capabilities
- ✅ **Container & VM inventory**: track physical hosts and the VMs/containers running on them
- ✅ **IT services tracker**: contracts, providers, costs, notice periods
- ✅ **PDF & CSV exports**: per-section reports for audits, budgets, hand-overs
- ✅ **HMAC-based authentication**: bcrypt password hashing, HMAC-signed cookies, in-memory rate limiting
- ✅ **Security headers**: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- ✅ **Single-file deployment**: SQLite + uvicorn + nginx; no Redis, no message queue, no migrations

## Comparison

| | This project | Snipe-IT / GLPI | Excel |
|---|---|---|---|
| Setup time | < 30 min | hours to days | trivial |
| Hardware footprint | < 100 MB RAM | several GB | 0 |
| Cross-platform agents | client scripts (no install) | agent-based | manual |
| Multi-tenant / RBAC | ❌ no | ✅ yes | ❌ no |
| Best fit | 50–200 devices, 1 org | 200+ devices, multi-team | < 30 devices |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/fidpa/device-inventory-fastapi
cd device-inventory-fastapi

# 2. Install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Generate AUTH_SECRET and AUTH_PASSWORD_HASH (commands inside .env.example)
# Set NEXTCLOUD_URL / NEXTCLOUD_USER / NEXTCLOUD_PASSWORD

# 4. Run
python3 -m uvicorn src.app:app --host 127.0.0.1 --port 8004

# 5. Open http://127.0.0.1:8004 → log in
```

For a production deployment (systemd, nginx reverse proxy, Let's Encrypt), see [`docs/how-to/deploy-systemd.md`](docs/how-to/deploy-systemd.md).

## Requirements

| Component | Minimum | Notes |
|-----------|---------|-------|
| Python | 3.10 | Type hints use modern syntax |
| FastAPI | 0.115 | Pinned in `requirements.txt` |
| SQLite | 3.35 | WAL mode + foreign keys |
| nginx | 1.18 | For HTTPS reverse proxy |
| systemd | any | For service management |
| Cloud storage | any WebDAV server | Nextcloud / ownCloud / Seafile |

## Architecture

```
┌──────────────────────────┐         ┌──────────────────────────┐
│  Windows / macOS / Linux │         │  Networked Printers      │
│  (end-user clients)      │         │  (SNMP)                  │
└────────────┬─────────────┘         └────────────┬─────────────┘
             │ collect-sysinfo.{ps1,py}           │ collect-printers.ps1
             │ writes JSON                        │ writes JSON
             ▼                                    ▼
┌──────────────────────────────────────────────────────────────┐
│              WebDAV server (Nextcloud / ownCloud)            │
│              /sysinfo/inbox/<files>.json                     │
└──────────────────────────┬───────────────────────────────────┘
                           │ scripts/import_sysinfo.py
                           │ scripts/import_printers.py
                           │ (systemd timer, every 1h or daily)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI (src/app.py)                                        │
│  ├─ HMAC auth + bcrypt + rate limiting                       │
│  ├─ Security headers middleware                              │
│  ├─ Jinja2 templates + vanilla JS                            │
│  └─ SQLite (WAL, foreign keys)                               │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTPS
                           ▼
                    nginx reverse proxy
                           │
                           ▼
                       Browser
```

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXTCLOUD_URL` | yes | Base URL of the WebDAV server (e.g. `https://cloud.example.com`) |
| `NEXTCLOUD_USER` | yes | WebDAV account name (e.g. `sysinfo`) |
| `NEXTCLOUD_PASSWORD` | yes | App password (NOT the login password) |
| `NEXTCLOUD_PATH` | yes | Path prefix for inbox files (e.g. `/remote.php/dav/files/sysinfo/inbox`) |
| `AUTH_PASSWORD_HASH` | yes | bcrypt hash of the application login password |
| `AUTH_SECRET` | yes | 32+ byte hex secret for HMAC cookie signing |

See [`.env.example`](.env.example) for the full list and helper commands.

## Project Structure

```
device-inventory-fastapi/
├── src/
│   └── app.py                    # FastAPI application (~2k LOC, single file)
├── scripts/
│   ├── import_sysinfo.py         # WebDAV → SQLite import (devices)
│   └── import_printers.py        # WebDAV → SQLite import (printers)
├── sysinfo/
│   ├── win/                      # Windows PowerShell collector
│   ├── mac/                      # macOS Python collector + .app build
│   ├── linux/                    # Linux Python collector
│   └── wts/                      # Windows Terminal Server printer collector
├── templates/                    # Jinja2 HTML templates
├── static/                       # CSS + vanilla JS
├── setup/
│   ├── setup.sh                  # One-shot installer
│   ├── systemd/                  # systemd unit + timer files
│   └── nginx/                    # nginx reverse-proxy example
├── tests/                        # pytest test suite
├── docs/                         # DIATAXIS-organized documentation
└── .github/workflows/            # CI: ruff lint + pytest
```

## Documentation

- 📖 **Tutorial**: [`docs/tutorial/01-quickstart.md`](docs/tutorial/01-quickstart.md) — first-time setup walk-through
- 🔧 **How-to guides**: [`docs/how-to/`](docs/how-to/) — task-oriented recipes (deploy, configure WebDAV, build the macOS app)
- 📚 **Reference**: [`docs/reference/`](docs/reference/) — API endpoints, database schema, environment variables
- 💡 **Explanation**: [`docs/explanation/`](docs/explanation/) — design rationale (why a single-file monolith, auth design, security headers)

## Known Limitations

- **Single-server**: SQLite + in-memory rate limiting → no horizontal scaling. For < 200 devices on a small VPS this is a feature, not a bug.
- **Single-tenant**: no organizations / role-based access control. One admin login, one inventory.
- **No agent**: client tools are run on demand by the end user. There is no scheduled push from the client side.
- **macOS Apple Silicon only** for the signed `.app` bundle. Build separately on Intel for an Intel binary.

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before submitting issues or pull requests, and report security issues privately as described in [`SECURITY.md`](SECURITY.md).

## Author

**Marc Allgeier** ([@fidpa](https://github.com/fidpa))

**Why I Built This**: After watching a client manage 80 devices across three Excel files — each a different version, each partly wrong — I wanted a tool that collects hardware specs automatically and keeps them current without asking IT to babysit an agent on every machine. The WebDAV + double-click approach came from watching what end users actually do: they run a script once if it's a `.bat` file, never if it requires an installer.

## License

MIT — see [`LICENSE`](LICENSE).
