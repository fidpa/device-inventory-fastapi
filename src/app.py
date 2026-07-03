# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""
Device Inventory — FastAPI server
Runs on server 192.0.2.10 at /opt/device-inventory/, port 8004.
Reads db/devices.db (SQLite), imports JSON files from Nextcloud via WebDAV.

Start:
  uvicorn app:app --host 127.0.0.1 --port 8004 --no-access-log
"""

import asyncio
import base64
import csv
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import bcrypt
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fpdf import FPDF, FontFace
from markupsafe import Markup
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("app.devices")

# Project root is one level above src/ (this file lives in src/app.py)
APP_DIR = Path(__file__).resolve().parent.parent
DB_PATH = APP_DIR / "db" / "devices.db"

# ─── Nextcloud-Configuration ─────────────────────────────────────────────────

_NC_URL = os.getenv("NEXTCLOUD_URL", "").rstrip("/")
_NC_USER = os.getenv("NEXTCLOUD_USER", "")
_NC_PASSWORD = os.getenv("NEXTCLOUD_PASSWORD", "")
_NC_PATH = os.getenv("NEXTCLOUD_PATH", "/remote.php/dav/files/sysinfo")


def _delete_nextcloud_file(filename: str) -> str | None:
    """WebDAV-DELETE on Nextcloud. Returns None on success, error message otherwise."""
    if not all([_NC_URL, _NC_USER, _NC_PASSWORD]):
        return "Nextcloud not configured"
    url = f"{_NC_URL}{_NC_PATH}/{filename}"
    try:
        resp = requests.delete(url, auth=(_NC_USER, _NC_PASSWORD), timeout=10)
        if resp.status_code in (200, 204, 404):
            return None  # OK — 404 means file was already gone
        return f"HTTP {resp.status_code}"
    except Exception as e:
        return str(e)


# ─── Auth-Configuration ──────────────────────────────────────────────────────

AUTH_PASSWORD_HASH: str = os.getenv("AUTH_PASSWORD_HASH", "")
AUTH_SECRET: str = os.getenv("AUTH_SECRET", "")
COOKIE_NAME = "inventory_auth"
COOKIE_MAX_AGE = 90 * 24 * 3600  # 90 Days
AUTH_SKIP = {"/login", "/health"}

if not AUTH_SECRET or len(AUTH_SECRET) < 32:
    raise SystemExit("ERROR: AUTH_SECRET not set or too short (min. 32 chars).")
if not AUTH_PASSWORD_HASH:
    raise SystemExit("ERROR: AUTH_PASSWORD_HASH not set.")


# ─── Token functions (HMAC-SHA256 signed) ──────────────────────────────────────


def _make_token() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(AUTH_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{ts}.{sig}".encode()).decode()


def _verify_token(token: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        ts_str, sig = raw.split(".", 1)
        if time.time() - int(ts_str) > COOKIE_MAX_AGE:
            return False
        expected = hmac.new(AUTH_SECRET.encode(), ts_str.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ─── Rate-Limiting (In-Memory, pro IP) ───────────────────────────────────────


def _client_ip(request: Request) -> str:
    """Determine the real client IP. Behind a reverse proxy request.client.host
    is always 127.0.0.1; nginx sets X-Real-IP to the client address (overwriting
    any client-supplied value, so it cannot be spoofed)."""
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


_rl_lock = threading.Lock()
_rl_attempts: dict[str, list[float]] = {}
_RL_MAX = 5
_RL_WINDOW = 60  # Seconds


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    with _rl_lock:
        attempts = [t for t in _rl_attempts.get(ip, []) if now - t < _RL_WINDOW]
        _rl_attempts[ip] = attempts
        return len(attempts) >= _RL_MAX


def _record_failed(ip: str) -> None:
    with _rl_lock:
        _rl_attempts.setdefault(ip, []).append(time.time())


def _clear_attempts(ip: str) -> None:
    with _rl_lock:
        _rl_attempts.pop(ip, None)


# ─── Security Headers Middleware ─────────────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        return response


# ─── Auth Middleware ──────────────────────────────────────────────────────────


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in AUTH_SKIP or path.startswith("/static/"):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if token and _verify_token(token):
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)


@asynccontextmanager
async def _lifespan(application: FastAPI):  # noqa: N803
    try:
        ensure_db()
        _seed_ctr_from_csv()
        log.info("Database ready: %s", DB_PATH)
    except Exception as e:
        log.error("DB initialization failed: %s", e)
    yield


app = FastAPI(title="Device Inventory", docs_url=None, redoc_url=None, lifespan=_lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


# ─── Template-Filter ─────────────────────────────────────────────────────────


def format_datetime(value: str) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, AttributeError):
        return value


templates.env.filters["datetime"] = format_datetime


def format_duration(start: str, end: str) -> str:
    if not end:
        return "running…"
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        delta = max(0, int((e - s).total_seconds()))
        if delta < 60:
            return f"{delta}s"
        return f"{delta // 60}m {delta % 60}s"
    except Exception:
        return "—"


templates.env.filters["duration"] = format_duration


def _tojson(value) -> Markup:
    return Markup(json.dumps(value, ensure_ascii=False))


def _euro(value) -> str:
    return f"{value:.2f} €" if value is not None else "—"


templates.env.filters["tojson"] = _tojson
templates.env.filters["euro"] = _euro


# ─── Database ─────────────────────────────────────────────────────────────


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # Wait on concurrent writes (import timer) instead of "database is locked"
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                file               TEXT UNIQUE NOT NULL,
                collected_at          TEXT,
                collected_by         TEXT,
                device_name         TEXT,
                device_manufacturer   TEXT,
                device_model       TEXT,
                device_serial_number TEXT,
                os_name             TEXT,
                os_version          TEXT,
                os_build            TEXT,
                cpu_description     TEXT,
                cpu_cores           INTEGER,
                ram_total_gb       REAL,
                json_payload           TEXT NOT NULL,
                imported_at       TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_devices_file ON devices(file);
            CREATE INDEX IF NOT EXISTS idx_devices_collected_by ON devices(collected_by);
            CREATE TABLE IF NOT EXISTS import_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at     TEXT NOT NULL,
                completed_am TEXT,
                new_devices     INTEGER DEFAULT 0,
                error           TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_import_log_started ON import_log(started_at DESC);
            CREATE TABLE IF NOT EXISTS printer_scans (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                file          TEXT UNIQUE NOT NULL,
                collected_at     TEXT,
                hostname       TEXT,
                printer_count INTEGER DEFAULT 0,
                json_payload      TEXT NOT NULL,
                imported_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_printer_scans_file ON printer_scans(file);
            CREATE TABLE IF NOT EXISTS it_services (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                description      TEXT NOT NULL,
                provider         TEXT,
                kategorie        TEXT DEFAULT 'Others',
                kosten           REAL,
                kosten_intervall TEXT DEFAULT 'monthly',
                vertrag_beginn   TEXT,
                vertrag_ende     TEXT,
                kuendigungsfrist TEXT,
                avv_present    INTEGER DEFAULT 0,
                avv_date        TEXT,
                kontakt          TEXT,
                note            TEXT,
                created_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_it_services_kategorie ON it_services(kategorie);
            CREATE TABLE IF NOT EXISTS printer_import_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at     TEXT NOT NULL,
                completed_am TEXT,
                new_scans       INTEGER DEFAULT 0,
                error           TEXT
            );
            CREATE TABLE IF NOT EXISTS ctr_hosts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname       TEXT NOT NULL,
                operating_system TEXT,
                cpu            TEXT,
                storage       TEXT,
                ram            TEXT,
                manufacturer_sn  TEXT
            );
            CREATE TABLE IF NOT EXISTS ctr_vms (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id    INTEGER NOT NULL REFERENCES ctr_hosts(id) ON DELETE CASCADE,
                name       TEXT NOT NULL,
                os         TEXT,
                vram       TEXT,
                vcpus      TEXT,
                usage TEXT
            );
        """)
        conn.commit()
        # Migrations: new columns for existing DBs without data loss add
        existing = {row[1] for row in conn.execute("PRAGMA table_info(devices)")}
        migrations = [
            ("note", "ALTER TABLE devices ADD COLUMN note TEXT"),
            ("status", "ALTER TABLE devices ADD COLUMN status TEXT DEFAULT 'active'"),
            ("issued_to", "ALTER TABLE devices ADD COLUMN issued_to TEXT"),
            ("output_since", "ALTER TABLE devices ADD COLUMN output_since TEXT"),
            ("device_type", "ALTER TABLE devices ADD COLUMN device_type TEXT DEFAULT 'unknown'"),
            ("accessories", "ALTER TABLE devices ADD COLUMN accessories TEXT"),
            ("vpn", "ALTER TABLE devices ADD COLUMN vpn TEXT"),
            ("inventory_number", "ALTER TABLE devices ADD COLUMN inventory_number TEXT"),
            ("location", "ALTER TABLE devices ADD COLUMN location TEXT"),
            ("acquisitionsdate", "ALTER TABLE devices ADD COLUMN acquisitionsdate TEXT"),
            ("acquisitionsprice", "ALTER TABLE devices ADD COLUMN acquisitionsprice REAL"),
            ("decommissioned_am", "ALTER TABLE devices ADD COLUMN decommissioned_am TEXT"),
        ]
        for col, sql in migrations:
            if col not in existing:
                conn.execute(sql)
                log.info("DB migration: column '%s' added", col)
        # Unique index for VPN (NULL allowed multiple times, values must be unique)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_vpn "
            "ON devices(vpn) WHERE vpn IS NOT NULL"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_inventory_number "
            "ON devices(inventory_number) WHERE inventory_number IS NOT NULL"
        )
        # Migration: add aktualisierte_device column to import_log for upsert tracking
        existing_log = {row[1] for row in conn.execute("PRAGMA table_info(import_log)")}
        if "aktualisierte_device" not in existing_log:
            conn.execute("ALTER TABLE import_log ADD COLUMN aktualisierte_device INTEGER DEFAULT 0")
            log.info("DB migration: import_log.aktualisierte_device added")
        conn.commit()
    finally:
        conn.close()


def _seed_ctr_from_csv() -> None:
    """CSV → SQLite one-time import, if ctr_hosts is empty."""
    csv_path = APP_DIR / "shared" / "Server.csv"
    if not csv_path.exists():
        return
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM ctr_hosts").fetchone()[0]
        if count > 0:
            return
        current_host_id: int | None = None
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                if row["Hostname"]:
                    cur = conn.execute(
                        "INSERT INTO ctr_hosts (hostname, operating_system, cpu, storage, ram, manufacturer_sn) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            row["Hostname"],
                            row["Operating System"],
                            row["CPU"],
                            row["Plattenstorage"],
                            row["RAM"],
                            row["Manufacturer and Serial Number"],
                        ),
                    )
                    current_host_id = cur.lastrowid
                if current_host_id and row["VMs"]:
                    conn.execute(
                        "INSERT INTO ctr_vms (host_id, name, os, vram, vcpus, usage) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            current_host_id,
                            row["VMs"],
                            row["VM OS"],
                            row["vRam in GB"],
                            row["vCPUs"],
                            row["Usage"],
                        ),
                    )
        conn.commit()
        log.info("CTR: CSV-Seed completed")
    except Exception as e:
        log.error("CTR CSV-Seed failed: %s", e)
    finally:
        conn.close()


# ─── Error Handler ──────────────────────────────────────────────────────────


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    status = exc.status_code
    messages = {
        404: "Page not found",
        503: "Service temporarily not available",
    }
    message = messages.get(status, f"Error {status}")
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": status, "message": message},
        status_code=status,
    )


# ─── Auth-Routen ───────────────────────────────────────────────────────────


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login-Page."""
    token = request.cookies.get(COOKIE_NAME)
    if token and _verify_token(token):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    """Verify password and set session cookie."""
    client_ip = _client_ip(request)

    if _is_rate_limited(client_ip):
        log.warning("Rate limit reached for %s", client_ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Too many attempts. Please wait a moment."},
            status_code=429,
        )

    form = await request.form()
    password = str(form.get("password", ""))

    if password and bcrypt.checkpw(password.encode(), AUTH_PASSWORD_HASH.encode()):
        _clear_attempts(client_ip)
        log.info("Login successful by %s", client_ip)
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key=COOKIE_NAME,
            value=_make_token(),
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=True,  # Site runs behind nginx with TLS; cookie only sent via HTTPS
        )
        return response

    _record_failed(client_ip)
    log.warning("Failed login by %s", client_ip)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Incorrect password."},
        status_code=401,
    )


@app.get("/logout")
async def logout():
    """Delete session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


# ─── HTML-Routen ───────────────────────────────────────────────────────────

VALID_TYPEN = {"desktop", "notebook", "thin-client", "printer", "unknown"}


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    q: str | None = Query(default=None),
    os: str | None = Query(default=None),
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
):
    """Inventorylist with Search, OS-, Status- and Type-Filter."""
    conn = get_db()
    try:
        conditions = []
        params: list = []

        if q:
            conditions.append(
                "(device_name LIKE ? OR collected_by LIKE ? OR device_model LIKE ? "
                "OR device_manufacturer LIKE ? OR device_serial_number LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like, like])

        if os:
            conditions.append("os_name LIKE ?")
            params.append(f"%{os}%")

        if status:
            conditions.append("status = ?")
            params.append(status)

        if type:
            conditions.append("COALESCE(device_type, 'unknown') = ?")
            params.append(type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        devices = conn.execute(
            f"SELECT id, file, collected_at, collected_by, device_name, device_manufacturer, "
            f"device_model, device_serial_number, os_name, os_version, os_build, "
            f"cpu_description, cpu_cores, ram_total_gb, imported_at, status, device_type "
            f"FROM devices {where} ORDER BY collected_at DESC",
            params,
        ).fetchall()

        os_options = conn.execute(
            "SELECT DISTINCT os_name FROM devices WHERE os_name IS NOT NULL ORDER BY os_name"
        ).fetchall()

        total = conn.execute(f"SELECT COUNT(*) FROM devices {where}", params).fetchone()[0]

        last_import_row = conn.execute(
            "SELECT MAX(imported_at) AS last_import FROM devices"
        ).fetchone()
        last_import = last_import_row["last_import"] if last_import_row else None

    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "devices": [dict(d) for d in devices],
            "os_options": [r["os_name"] for r in os_options],
            "q": q or "",
            "os_filter": os or "",
            "status_filter": status or "",
            "type_filter": type or "",
            "total": total,
            "last_import": last_import,
        },
    )


@app.get("/device/{device_id}", response_class=HTMLResponse)
async def device_detail(request: Request, device_id: int):
    """Device detail: show all JSON fields."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    device = dict(row)
    try:
        device["json_parsed"] = json.loads(device["json_payload"])
    except (json.JSONDecodeError, KeyError):
        device["json_parsed"] = {}

    accessories_raw = device.get("accessories")
    try:
        accessory_data = json.loads(accessories_raw) if accessories_raw else {}
    except (json.JSONDecodeError, TypeError):
        accessory_data = {}

    return templates.TemplateResponse(
        request,
        "device.html",
        {
            "device": device,
            "valid_status": ["active", "inactive", "decommissioned"],
            "valid_types": ["desktop", "notebook", "thin-client", "printer", "unknown"],
            "accessory_data": accessory_data,
            "accessory_types": [
                ("monitor", "Monitor"),
                ("maus", "Mouse"),
                ("tastatur", "Keyboard"),
                ("netzteil", "Power supply / charging cable"),
                ("docking", "Dockingstation"),
                ("headset", "Headset"),
                ("laptoptasche", "Laptop bag / backpack"),
                ("usb_hub", "USB-Hub"),
            ],
        },
    )


# ─── API-Routen ────────────────────────────────────────────────────────────


@app.post("/api/import")
async def api_import(request: Request):
    """Trigger Nextcloud import and return status."""
    client_ip = _client_ip(request)
    log.info("Import requested by %s", client_ip)

    import_script = APP_DIR / "scripts" / "import_sysinfo.py"
    if not import_script.exists():
        raise HTTPException(status_code=500, detail="Import script not found")

    try:
        # to_thread: subprocess.run would otherwise block the event loop for up to 120s
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(import_script)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(APP_DIR),
        )
        if result.returncode != 0:
            log.error("Import failed (by %s): %s", client_ip, result.stderr)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": result.stderr[-500:]},
            )
        log.info("Import completed (by %s): %s", client_ip, result.stdout[-200:])
        return {"status": "ok", "output": result.stdout[-500:]}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Import-Timeout (120s)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


VALID_STATUS = {"active", "inactive", "decommissioned"}
VALID_CATEGORIES = {"SaaS", "Maintenance", "Telekommunikation", "Abrechnung", "Others"}
VALID_INTERVALLE = {"monthly", "yearly", "once"}
_CATEGORIEN_LIST = ["SaaS", "Maintenance", "Telekommunikation", "Abrechnung", "Others"]
_INTERVALLE_LIST = ["monthly", "yearly", "once"]


@app.patch("/api/device/{device_id}")
async def api_patch_device(request: Request, device_id: int):
    """Update device status, assignment, type or note."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    allowed = {
        "status",
        "issued_to",
        "output_since",
        "note",
        "device_type",
        "accessories",
        "collected_by",
        "vpn",
        "inventory_number",
        "location",
        "acquisitionsdate",
        "acquisitionsprice",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields provided")

    if (
        "status" in updates
        and updates["status"] is not None
        and updates["status"] not in VALID_STATUS
    ):
        raise HTTPException(status_code=400, detail=f"Invalid status: {updates['status']}")

    if (
        "device_type" in updates
        and updates["device_type"] is not None
        and updates["device_type"] not in VALID_TYPEN
    ):
        raise HTTPException(
            status_code=400, detail=f"Invalid device type: {updates['device_type']}"
        )

    if "acquisitionsprice" in updates and updates["acquisitionsprice"] is not None:
        try:
            price = float(updates["acquisitionsprice"])
            if price < 0:
                raise ValueError
            updates["acquisitionsprice"] = price
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid acquisition price")

    if "acquisitionsdate" in updates and updates["acquisitionsdate"] is not None:
        try:
            datetime.strptime(updates["acquisitionsdate"], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid acquisition date (format: YYYY-MM-DD)"
            )

    if "accessories" in updates:
        val = updates["accessories"]
        if val is not None:
            if not isinstance(val, dict):
                raise HTTPException(
                    status_code=400, detail="accessories must be a JSON object or null"
                )
            updates["accessories"] = json.dumps(val, ensure_ascii=False)

    # decommissioned_am: set/clear automatically on status change
    if "status" in updates:
        conn_check = get_db()
        try:
            current = conn_check.execute(
                "SELECT status, decommissioned_am FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="Device not found")
            old_status = current["status"]
            new_status = updates["status"]
            if new_status == "decommissioned" and old_status != "decommissioned":
                if not current["decommissioned_am"]:
                    updates["decommissioned_am"] = datetime.now().strftime("%Y-%m-%d")
            elif new_status != "decommissioned" and old_status == "decommissioned":
                updates["decommissioned_am"] = None
        finally:
            conn_check.close()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [device_id]

    conn = get_db()
    try:
        cur = conn.execute(f"UPDATE devices SET {set_clause} WHERE id = ?", values)
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
    except sqlite3.IntegrityError as e:
        if "inventory_number" in str(e):
            raise HTTPException(status_code=409, detail="Inventory number already in use")
        raise HTTPException(status_code=409, detail="VPN number already in use")
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()

    return {"status": "ok"}


@app.delete("/api/device/{device_id}")
async def api_delete_device(device_id: int):
    """Delete device from database and remove JSON from Nextcloud."""
    conn = get_db()
    try:
        row = conn.execute("SELECT file FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Device not found")
        file = row["file"]
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        conn.commit()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()

    # Nextcloud-JSON removal (best-effort — DB-Deletion has already occurred)
    nc_error = _delete_nextcloud_file(file)
    if nc_error:
        log.warning("Nextcloud file '%s' could not be deleted: %s", file, nc_error)
        return {
            "status": "ok",
            "warning": f"Device deleted, Nextcloud-File '{file}' must be manually removed ({nc_error})",
        }

    log.info("Device %s and Nextcloud file '%s' deleted", device_id, file)
    return {"status": "ok"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Statistics dashboard."""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        avg_ram_row = conn.execute(
            "SELECT ROUND(AVG(ram_total_gb), 1) FROM devices WHERE ram_total_gb IS NOT NULL"
        ).fetchone()
        avg_ram = avg_ram_row[0] if avg_ram_row else None

        ohne_assignment = conn.execute(
            "SELECT COUNT(*) FROM devices WHERE issued_to IS NULL OR issued_to = ''"
        ).fetchone()[0]

        ohne_inventory_number = conn.execute(
            "SELECT COUNT(*) FROM devices WHERE inventory_number IS NULL"
        ).fetchone()[0]

        dates_row = conn.execute(
            "SELECT MIN(collected_at) AS oldest, MAX(collected_at) AS newest FROM devices"
        ).fetchone()
        oldest = dates_row["oldest"] if dates_row else None
        newest = dates_row["newest"] if dates_row else None

        latest_import_row = conn.execute("SELECT MAX(imported_at) FROM devices").fetchone()
        latest_import = latest_import_row[0] if latest_import_row else None

        os_stats = conn.execute(
            "SELECT os_name, COUNT(*) AS count FROM devices "
            "WHERE os_name IS NOT NULL GROUP BY os_name ORDER BY count DESC LIMIT 10"
        ).fetchall()

        status_stats = conn.execute(
            "SELECT COALESCE(status, 'active') AS status, COUNT(*) AS count "
            "FROM devices GROUP BY status ORDER BY count DESC"
        ).fetchall()

    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "total": total,
            "avg_ram": avg_ram,
            "ohne_assignment": ohne_assignment,
            "ohne_inventory_number": ohne_inventory_number,
            "oldest": oldest,
            "newest": newest,
            "latest_import": latest_import,
            "os_stats": [dict(r) for r in os_stats],
            "status_stats": [dict(r) for r in status_stats],
        },
    )


VPN_RANGE = range(1, 65)  # 1–64


@app.get("/vpn", response_class=HTMLResponse)
async def vpn_overview(request: Request):
    """VPN number overview (1–64)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, device_name, issued_to, vpn FROM devices WHERE vpn IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    assigned_vpn = {}
    other = []
    for r in rows:
        m = re.search(r"\d+", str(r["vpn"]))
        if m:
            nr = int(m.group())
            if nr in VPN_RANGE:
                assigned_vpn[nr] = dict(r)
            else:
                other.append(dict(r))
        else:
            other.append(dict(r))

    return templates.TemplateResponse(
        request,
        "vpn.html",
        {
            "vpn_range": list(VPN_RANGE),
            "assigned": assigned_vpn,
            "other": other,
            "count_assigned": len(assigned_vpn),
            "count_free": len(VPN_RANGE) - len(assigned_vpn),
            "total": len(VPN_RANGE),
        },
    )


@app.get("/import/log", response_class=HTMLResponse)
async def import_log_page(request: Request):
    """Import history as HTML page."""
    conn = get_db()
    try:
        entries = conn.execute(
            "SELECT * FROM import_log ORDER BY started_at DESC LIMIT 100"
        ).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "import_log.html",
        {
            "entries": [dict(e) for e in entries],
        },
    )


# ─── PDF-Export Helpers ──────────────────────────────────────────────────────


def _pdf_s(val, max_len: int = 55) -> str:
    """None → '-', truncates if needed, encodes to Latin-1 (core-fonts)."""
    if val is None:
        return "-"
    s = str(val)
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _eur(val: float) -> str:
    """Format a euro amount in German locale: 1.234,56 EUR."""
    return f"{val:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")


def _build_devices_pdf(rows, subtitle: str = "") -> bytes:
    """Build the device-inventory PDF (A4 landscape) and return bytes."""

    class _PDF(FPDF):
        _export_dt = datetime.now().strftime("%d.%m.%Y %H:%M")

        def header(self):
            self.set_fill_color(26, 115, 232)
            self.rect(self.l_margin, 5, self.epw, 13, "F")
            self.set_text_color(255, 255, 255)
            self.set_font("Helvetica", "B", 12)
            self.set_xy(self.l_margin + 3, 6)
            self.cell(80, 9, "Example Organization", ln=False)
            self.set_font("Helvetica", "", 10)
            self.set_xy(self.l_margin, 6)
            self.cell(self.epw - 3, 9, "Device Inventory", align="R")
            self.ln(22)

        def footer(self):
            self.set_y(-12)
            self.set_text_color(108, 117, 125)
            self.set_font("Helvetica", "", 8)
            self.set_x(self.l_margin)
            self.cell(self.epw / 2, 5, self._export_dt, align="L")
            self.cell(self.epw / 2, 5, f"Page {self.page_no()}/{{nb}}", align="R")

    pdf = _PDF(orientation="L", format="A4")
    pdf.alias_nb_pages()
    pdf.set_margins(12, 6, 12)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    # Subtitle
    pdf.set_text_color(108, 117, 125)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0, 5, subtitle or f"{len(rows)} Devices | As of: {datetime.now().strftime('%d.%m.%Y')}"
    )
    pdf.ln(7)

    pdf.set_text_color(33, 37, 41)
    pdf.set_font("Helvetica", "", 8.5)

    # Column widths: sum = 273mm = epw (297 - 12 - 12)
    COL_W = (22, 50, 35, 57, 32, 22, 28, 27)
    HDRS = [
        "Inventorynr.",
        "Device Name",
        "User",
        "Manufacturer / Model",
        "Location",
        "Status",
        "Acquisition",
        "Price net",
    ]
    h_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=(26, 115, 232))

    with pdf.table(
        borders_layout="MINIMAL",
        cell_fill_color=(245, 246, 247),
        cell_fill_mode="ROWS",
        col_widths=COL_W,
        headings_style=h_style,
        line_height=5.5,
        text_align="LEFT",
        first_row_as_headings=True,
    ) as table:
        hrow = table.row()
        for h in HDRS:
            hrow.cell(h)
        for r in rows:
            row = table.row()
            row.cell(_pdf_s(r["inventory_number"]))
            row.cell(_pdf_s(r["device_name"]))
            row.cell(_pdf_s(r["collected_by"]))
            hm = " ".join(filter(None, [r["device_manufacturer"], r["device_model"]]))
            row.cell(_pdf_s(hm) or "-")
            row.cell(_pdf_s(r["location"]))
            row.cell(_pdf_s(r["status"]))
            row.cell(_pdf_s(r["acquisitionsdate"]))
            row.cell(_eur(r["acquisitionsprice"]) if r["acquisitionsprice"] is not None else "-")

    return bytes(pdf.output())


def _build_services_pdf(rows) -> bytes:
    """Build the IT-services PDF (A4 portrait) and return bytes."""
    MULTIPLIERS = {"monthly": 12, "quarterly": 4, "semi-annual": 2, "yearly": 1}

    total_annual = 0.0
    enriched = []
    for r in rows:
        k = r["kosten"]
        ivl = r["kosten_intervall"] or "yearly"
        # "once" (and unknown intervals) must not count towards annual costs
        yeares = (k * MULTIPLIERS[ivl]) if (k is not None and ivl in MULTIPLIERS) else None
        if yeares:
            total_annual += yeares
        enriched.append((r, yeares))

    class _PDF(FPDF):
        _export_dt = datetime.now().strftime("%d.%m.%Y %H:%M")

        def header(self):
            self.set_fill_color(26, 115, 232)
            self.rect(self.l_margin, 5, self.epw, 13, "F")
            self.set_text_color(255, 255, 255)
            self.set_font("Helvetica", "B", 12)
            self.set_xy(self.l_margin + 3, 6)
            self.cell(80, 9, "Example Organization", ln=False)
            self.set_font("Helvetica", "", 10)
            self.set_xy(self.l_margin, 6)
            self.cell(self.epw - 3, 9, "IT-Services", align="R")
            self.ln(22)

        def footer(self):
            self.set_y(-12)
            self.set_text_color(108, 117, 125)
            self.set_font("Helvetica", "", 8)
            self.set_x(self.l_margin)
            self.cell(self.epw / 2, 5, self._export_dt, align="L")
            self.cell(self.epw / 2, 5, f"Page {self.page_no()}/{{nb}}", align="R")

    pdf = _PDF(orientation="P", format="A4")
    pdf.alias_nb_pages()
    pdf.set_margins(15, 6, 15)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    # Subtitle with total cost
    pdf.set_text_color(108, 117, 125)
    pdf.set_font("Helvetica", "", 9)
    total_str = _eur(total_annual) if total_annual else "-"
    pdf.cell(
        0,
        5,
        f"{len(enriched)} Services | Total cost/year: {total_str} | As of: {datetime.now().strftime('%d.%m.%Y')}",
    )
    pdf.ln(7)

    pdf.set_text_color(33, 37, 41)
    pdf.set_font("Helvetica", "", 9)

    # Column widths: sum = 180mm = epw (210 - 15 - 15)
    COL_W = (48, 38, 25, 28, 23, 18)
    HDRS = ["Description", "Provider", "Category", "Cost/Year", "Contract until", "DPA"]
    h_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=(26, 115, 232))

    with pdf.table(
        borders_layout="MINIMAL",
        cell_fill_color=(245, 246, 247),
        cell_fill_mode="ROWS",
        col_widths=COL_W,
        headings_style=h_style,
        line_height=6,
        text_align="LEFT",
        first_row_as_headings=True,
    ) as table:
        hrow = table.row()
        for h in HDRS:
            hrow.cell(h)
        for r, yeares in enriched:
            row = table.row()
            row.cell(_pdf_s(r["description"]))
            row.cell(_pdf_s(r["provider"]))
            row.cell(_pdf_s(r["kategorie"]))
            row.cell(_eur(yeares) if yeares is not None else "-")
            row.cell(_pdf_s(r["vertrag_ende"]))
            row.cell("Yes" if r["avv_present"] else "No")

    # Total row
    if total_annual:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(33, 37, 41)
        pdf.cell(0, 6, f"Total cost/year: {_eur(total_annual)}", align="R")

    return bytes(pdf.output())


@app.get("/export/pdf")
async def export_pdf(
    request: Request,
    q: str | None = Query(default=None),
    os: str | None = Query(default=None),
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
):
    """Export device list as PDF (same filters as the overview)."""
    conn = get_db()
    try:
        conditions: list = []
        params: list = []
        if q:
            like = f"%{q}%"
            conditions.append(
                "(device_name LIKE ? OR collected_by LIKE ? OR device_model LIKE ? "
                "OR device_manufacturer LIKE ? OR device_serial_number LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        if os:
            conditions.append("os_name LIKE ?")
            params.append(f"%{os}%")
        if status:
            conditions.append("status = ?")
            params.append(status)
        if type:
            conditions.append("COALESCE(device_type, 'unknown') = ?")
            params.append(type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT file, collected_by, device_name, device_manufacturer, device_model, "
            f"device_serial_number, os_name, os_version, cpu_description, cpu_cores, "
            f"ram_total_gb, COALESCE(device_type, 'unknown') AS device_type, "
            f"status, issued_to, output_since, "
            f"inventory_number, location, acquisitionsdate, acquisitionsprice, decommissioned_am, "
            f"collected_at, imported_at "
            f"FROM devices {where} ORDER BY collected_at DESC",
            params,
        ).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    parts = []
    if q:
        parts.append(f"Search: {q}")
    if os:
        parts.append(f"OS: {os}")
    if status:
        parts.append(f"Status: {status}")
    if type:
        parts.append(f"Type: {type}")
    subtitle = f"{len(rows)} Devices | As of: {datetime.now().strftime('%d.%m.%Y')}"
    if parts:
        subtitle += " | Filter: " + ", ".join(parts)

    pdf_bytes = _build_devices_pdf(rows, subtitle)
    filename = f"device-inventory-{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_ctr_pdf(hosts: list[dict]) -> bytes:
    """Build the CTR server PDF (A4 portrait) and return bytes."""

    class _PDF(FPDF):
        _export_dt = datetime.now().strftime("%d.%m.%Y %H:%M")

        def header(self):
            self.set_fill_color(26, 115, 232)
            self.rect(self.l_margin, 5, self.epw, 13, "F")
            self.set_text_color(255, 255, 255)
            self.set_font("Helvetica", "B", 12)
            self.set_xy(self.l_margin + 3, 6)
            self.cell(80, 9, "Example Organization", ln=False)
            self.set_font("Helvetica", "", 10)
            self.set_xy(self.l_margin, 6)
            self.cell(self.epw - 3, 9, "CTR Server", align="R")
            self.ln(22)

        def footer(self):
            self.set_y(-12)
            self.set_text_color(108, 117, 125)
            self.set_font("Helvetica", "", 8)
            self.set_x(self.l_margin)
            self.cell(self.epw / 2, 5, self._export_dt, align="L")
            self.cell(self.epw / 2, 5, f"Page {self.page_no()}/{{nb}}", align="R")

    pdf = _PDF(orientation="P", format="A4")
    pdf.alias_nb_pages()
    pdf.set_margins(15, 6, 15)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    total_vms = sum(len(h.get("vms", [])) for h in hosts)
    pdf.set_text_color(108, 117, 125)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0, 5, f"{len(hosts)} Hosts | {total_vms} VMs | Stand: {datetime.now().strftime('%d.%m.%Y')}"
    )
    pdf.ln(8)

    h_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=(26, 115, 232))
    VM_COL_W = (38, 52, 18, 16, 56)
    VM_HDRS = ["Name", "Operating System", "vRAM GB", "vCPUs", "Usage"]

    for host in hosts:
        # Host heading
        pdf.set_fill_color(240, 244, 255)
        pdf.set_text_color(26, 115, 232)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, _pdf_s(host["hostname"], 80), fill=True, ln=True)
        pdf.ln(1)

        # Host-Metadaten
        pdf.set_text_color(33, 37, 41)
        pdf.set_font("Helvetica", "", 8)
        meta_pairs = [
            ("BS", host.get("operating_system")),
            ("CPU", host.get("cpu")),
            ("Storage", host.get("storage")),
            ("RAM", host.get("ram")),
            ("SN", host.get("manufacturer_sn")),
        ]
        for label, val in meta_pairs:
            if val:
                pdf.set_font("Helvetica", "B", 8)
                pdf.cell(20, 5, label + ":", ln=False)
                pdf.set_font("Helvetica", "", 8)
                pdf.cell(0, 5, _pdf_s(val, 100), ln=True)
        pdf.ln(2)

        # VM-Table
        vms = host.get("vms", [])
        if vms:
            pdf.set_font("Helvetica", "", 8)
            with pdf.table(
                borders_layout="MINIMAL",
                cell_fill_color=(245, 246, 247),
                cell_fill_mode="ROWS",
                col_widths=VM_COL_W,
                headings_style=h_style,
                line_height=5,
                text_align="LEFT",
                first_row_as_headings=True,
            ) as table:
                hrow = table.row()
                for h in VM_HDRS:
                    hrow.cell(h)
                for vm in vms:
                    row = table.row()
                    row.cell(_pdf_s(vm["name"], 35))
                    row.cell(_pdf_s(vm.get("os"), 50))
                    row.cell(_pdf_s(vm.get("vram"), 10))
                    row.cell(_pdf_s(vm.get("vcpus"), 8))
                    row.cell(_pdf_s(vm.get("usage"), 55))
        else:
            pdf.set_text_color(108, 117, 125)
            pdf.set_font("Helvetica", "I", 8)
            pdf.cell(0, 5, "No VMs collected.", ln=True)

        pdf.ln(5)

    return bytes(pdf.output())


@app.get("/export/services/pdf")
async def export_services_pdf():
    """Export IT services as PDF."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM it_services ORDER BY kategorie, description").fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    pdf_bytes = _build_services_pdf(rows)
    filename = f"services-{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/csv")
async def export_csv(
    q: str | None = Query(default=None),
    os: str | None = Query(default=None),
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
):
    """Export inventory list as CSV (same filters as the overview)."""
    conn = get_db()
    try:
        conditions = []
        params: list = []
        if q:
            like = f"%{q}%"
            conditions.append(
                "(device_name LIKE ? OR collected_by LIKE ? OR device_model LIKE ? "
                "OR device_manufacturer LIKE ? OR device_serial_number LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        if os:
            conditions.append("os_name LIKE ?")
            params.append(f"%{os}%")
        if status:
            conditions.append("status = ?")
            params.append(status)
        if type:
            conditions.append("COALESCE(device_type, 'unknown') = ?")
            params.append(type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT file, collected_by, device_name, device_manufacturer, device_model, "
            f"device_serial_number, os_name, os_version, cpu_description, cpu_cores, "
            f"ram_total_gb, COALESCE(device_type, 'unknown') AS device_type, "
            f"status, issued_to, output_since, "
            f"inventory_number, location, acquisitionsdate, acquisitionsprice, decommissioned_am, "
            f"collected_at, imported_at "
            f"FROM devices {where} ORDER BY collected_at DESC",
            params,
        ).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "File",
            "User",
            "Device name",
            "Manufacturer",
            "Model",
            "Serial Number",
            "OS",
            "OS-Version",
            "CPU",
            "Cores",
            "RAM (GB)",
            "Device Type",
            "Status",
            "Issued to",
            "Since",
            "Inventory Number",
            "Location",
            "Acquisitionsdate",
            "Acquisitionsprice (EUR)",
            "Decommissioned on",
            "Collected at",
            "Imported at",
        ]
    )
    for r in rows:
        writer.writerow(list(r))

    filename = f"device-inventory-{datetime.now().strftime('%Y%m%d')}.csv"
    return PlainTextResponse(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/health", response_class=PlainTextResponse)
async def health():
    """Health check endpoint (no auth required)."""
    return "OK"


# ─── Printers-Routen ─────────────────────────────────────────────────────────


@app.get("/printers", response_class=HTMLResponse)
async def printers(
    request: Request,
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    location: str | None = Query(default=None),
):
    """Printers overview: latest scan from printer_scans."""
    conn = get_db()
    try:
        scan_row = conn.execute(
            "SELECT * FROM printer_scans ORDER BY collected_at DESC LIMIT 1"
        ).fetchone()
        alle_scans = conn.execute(
            "SELECT id, hostname, file, collected_at FROM printer_scans ORDER BY collected_at DESC"
        ).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    if not scan_row:
        return templates.TemplateResponse(
            request,
            "printers.html",
            {
                "scan": None,
                "alle_scans": [],
                "printer": [],
                "locations": [],
                "q": q or "",
                "status_filter": status or "",
                "location_filter": location or "",
            },
        )

    scan = dict(scan_row)
    try:
        data = json.loads(scan["json_payload"])
    except (json.JSONDecodeError, KeyError):
        data = {}

    alle_printer = data.get("printer") or []

    # Apply filters
    printer = alle_printer
    if q:
        ql = q.lower()
        printer = [
            d
            for d in printer
            if ql in (d.get("name") or "").lower()
            or ql in (d.get("ip_address") or "").lower()
            or ql in ((d.get("snmp") or {}).get("model") or "").lower()
            or ql in (d.get("location") or "").lower()
            or ql in (d.get("treiber") or "").lower()  # driver field from WTS script
        ]
    if status:
        printer = [d for d in printer if d.get("status") == status]
    if location:
        printer = [d for d in printer if d.get("location") == location]

    # Location list for filter dropdown (built dynamically from data)
    locations = sorted({d.get("location") for d in alle_printer if d.get("location")})

    return templates.TemplateResponse(
        request,
        "printers.html",
        {
            "scan": scan,
            "alle_scans": [dict(r) for r in alle_scans],
            "printer": printer,
            "locations": locations,
            "q": q or "",
            "status_filter": status or "",
            "location_filter": location or "",
        },
    )


@app.get("/printer/{scan_id}", response_class=HTMLResponse)
async def printer_detail(request: Request, scan_id: int):
    """Printer scan detail: all printers in scan with SNMP data."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM printer_scans WHERE id = ?", (scan_id,)).fetchone()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id} not found")

    scan = dict(row)
    try:
        data = json.loads(scan["json_payload"])
    except (json.JSONDecodeError, KeyError):
        data = {}

    return templates.TemplateResponse(
        request,
        "printer_detail.html",
        {
            "scan": scan,
            "printer": data.get("printer") or [],
            "collected_at": data.get("collected_at"),
            "collected_by": data.get("collected_by"),
        },
    )


@app.get("/export/printers/csv")
async def export_printers_csv(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    location: str | None = Query(default=None),
):
    """Export printer list as CSV (latest scan, same filters as /printers)."""
    conn = get_db()
    try:
        scan_row = conn.execute(
            "SELECT json_payload FROM printer_scans ORDER BY collected_at DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    alle_printer: list = []
    if scan_row:
        try:
            alle_printer = json.loads(scan_row["json_payload"]).get("printer") or []
        except (json.JSONDecodeError, KeyError):
            pass

    printer = alle_printer
    if q:
        ql = q.lower()
        printer = [
            d
            for d in printer
            if ql in (d.get("name") or "").lower()
            or ql in (d.get("ip_address") or "").lower()
            or ql in ((d.get("snmp") or {}).get("model") or "").lower()
            or ql in (d.get("location") or "").lower()
        ]
    if status:
        printer = [d for d in printer if d.get("status") == status]
    if location:
        printer = [d for d in printer if d.get("location") == location]

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Name",
            "IP-Address",
            "Port",
            "Driver",
            "Location",
            "Status",
            "Color",
            "Duplex",
            "Model (SNMP)",
            "Manufacturer (SNMP)",
            "Serial Number (SNMP)",
            "Pages total",
            "Pages Color",
        ]
    )
    for d in printer:
        snmp = d.get("snmp") or {}
        writer.writerow(
            [
                d.get("name") or "",
                d.get("ip_address") or "",
                d.get("port_number") or "",
                d.get("treiber") or "",
                d.get("location") or "",
                d.get("status") or "",
                "Yes" if d.get("color") else "No",
                "Yes" if d.get("duplex") else "No",
                snmp.get("model") or "",
                snmp.get("manufacturer") or "",
                snmp.get("serial_number") or "",
                snmp.get("pages_total") or "",
                snmp.get("pages_color") or "",
            ]
        )

    filename = f"printers-{datetime.now().strftime('%Y%m%d')}.csv"
    return PlainTextResponse(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/import/printers")
async def api_import_printers(request: Request):
    """Trigger printer import from Nextcloud."""
    client_ip = _client_ip(request)
    log.info("Printer import requested by %s", client_ip)

    import_script = APP_DIR / "scripts" / "import_printers.py"
    if not import_script.exists():
        raise HTTPException(status_code=500, detail="Import script not found")

    try:
        # to_thread: subprocess.run would otherwise block the event loop for up to 120s
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(import_script)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(APP_DIR),
        )
        if result.returncode != 0:
            log.error("Printers-Import failed (by %s): %s", client_ip, result.stderr)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": result.stderr[-500:]},
            )
        log.info("Printers-Import completed (by %s): %s", client_ip, result.stdout[-200:])
        return {"status": "ok", "output": result.stdout[-500:]}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Import-Timeout (120s)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/printer-scan/{scan_id}")
async def delete_printer_scan(scan_id: int, request: Request):
    """Deletes a printer scan entry (e.g. after WTS-Migration)."""
    conn = get_db()
    try:
        row = conn.execute("SELECT hostname FROM printer_scans WHERE id = ?", (scan_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Scan not found")
        conn.execute("DELETE FROM printer_scans WHERE id = ?", (scan_id,))
        conn.commit()
        log.info(
            "Printer scan %s (%s) deleted by %s", scan_id, row["hostname"], _client_ip(request)
        )
        return {"status": "ok", "deleted": scan_id, "hostname": row["hostname"]}
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()


# ─── CTR-Routen ──────────────────────────────────────────────────────────────


@app.get("/ctr", response_class=HTMLResponse)
async def ctr_page(request: Request):
    """CTR server infrastructure overview."""
    conn = get_db()
    try:
        host_rows = conn.execute("SELECT * FROM ctr_hosts ORDER BY id").fetchall()
        vm_rows = conn.execute("SELECT * FROM ctr_vms ORDER BY host_id, id").fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    vms_by_host: dict[int, list[dict]] = {}
    for vm in vm_rows:
        vms_by_host.setdefault(vm["host_id"], []).append(dict(vm))

    hosts = []
    for h in host_rows:
        host = dict(h)
        host["vms"] = vms_by_host.get(h["id"], [])
        hosts.append(host)

    return templates.TemplateResponse(request, "ctr.html", {"hosts": hosts})


@app.post("/api/ctr/hosts", status_code=201)
async def api_ctr_create_host(request: Request):
    """Create new CTR host."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    hostname = (body.get("hostname") or "").strip()
    if not hostname:
        raise HTTPException(status_code=400, detail="Hostname is required")
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO ctr_hosts (hostname, operating_system, cpu, storage, ram, manufacturer_sn) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                hostname,
                body.get("operating_system") or None,
                body.get("cpu") or None,
                body.get("storage") or None,
                body.get("ram") or None,
                body.get("manufacturer_sn") or None,
            ),
        )
        conn.commit()
        return {"status": "ok", "id": cur.lastrowid}
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()


@app.patch("/api/ctr/host/{host_id}")
async def api_ctr_patch_host(request: Request, host_id: int):
    """Edit CTR host."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    hostname = (body.get("hostname") or "").strip()
    if not hostname:
        raise HTTPException(status_code=400, detail="Hostname is required")
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE ctr_hosts SET hostname=?, operating_system=?, cpu=?, storage=?, ram=?, manufacturer_sn=? "
            "WHERE id=?",
            (
                hostname,
                body.get("operating_system") or None,
                body.get("cpu") or None,
                body.get("storage") or None,
                body.get("ram") or None,
                body.get("manufacturer_sn") or None,
                host_id,
            ),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Host not found")
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB error: {e}")
    finally:
        conn.close()
    return {"status": "ok"}


@app.delete("/api/ctr/host/{host_id}")
async def api_ctr_delete_host(host_id: int):
    """Delete CTR host (including VMs via CASCADE)."""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM ctr_hosts WHERE id=?", (host_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Host not found")
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()
    return {"status": "ok"}


@app.post("/api/ctr/host/{host_id}/vms", status_code=201)
async def api_ctr_create_vm(request: Request, host_id: int):
    """Create new VM under a host."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="VM name is required")
    conn = get_db()
    try:
        host = conn.execute("SELECT id FROM ctr_hosts WHERE id=?", (host_id,)).fetchone()
        if not host:
            raise HTTPException(status_code=404, detail="Host not found")
        cur = conn.execute(
            "INSERT INTO ctr_vms (host_id, name, os, vram, vcpus, usage) VALUES (?, ?, ?, ?, ?, ?)",
            (
                host_id,
                name,
                body.get("os") or None,
                body.get("vram") or None,
                body.get("vcpus") or None,
                body.get("usage") or None,
            ),
        )
        conn.commit()
        return {"status": "ok", "id": cur.lastrowid}
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()


@app.patch("/api/ctr/vm/{vm_id}")
async def api_ctr_patch_vm(request: Request, vm_id: int):
    """Edit CTR VM."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="VM name is required")
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE ctr_vms SET name=?, os=?, vram=?, vcpus=?, usage=? WHERE id=?",
            (
                name,
                body.get("os") or None,
                body.get("vram") or None,
                body.get("vcpus") or None,
                body.get("usage") or None,
                vm_id,
            ),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="VM not found")
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB error: {e}")
    finally:
        conn.close()
    return {"status": "ok"}


@app.delete("/api/ctr/vm/{vm_id}")
async def api_ctr_delete_vm(vm_id: int):
    """Delete CTR VM."""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM ctr_vms WHERE id=?", (vm_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="VM not found")
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()
    return {"status": "ok"}


@app.get("/export/ctr/pdf")
async def export_ctr_pdf():
    """Export CTR servers as PDF."""
    conn = get_db()
    try:
        host_rows = conn.execute("SELECT * FROM ctr_hosts ORDER BY id").fetchall()
        vm_rows = conn.execute("SELECT * FROM ctr_vms ORDER BY host_id, id").fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    vms_by_host: dict[int, list[dict]] = {}
    for vm in vm_rows:
        vms_by_host.setdefault(vm["host_id"], []).append(dict(vm))

    hosts = []
    for h in host_rows:
        host = dict(h)
        host["vms"] = vms_by_host.get(h["id"], [])
        hosts.append(host)

    pdf_bytes = _build_ctr_pdf(hosts)
    filename = f"ctr-servers-{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── IT-Services-Routen ─────────────────────────────────────────────────────


@app.get("/services", response_class=HTMLResponse)
async def services_page(request: Request):
    """IT services overview."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM it_services ORDER BY kategorie, description").fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "services.html",
        {
            "services": [dict(r) for r in rows],
            "kategorien": _CATEGORIEN_LIST,
            "intervalle": _INTERVALLE_LIST,
        },
    )


@app.get("/export/services/csv")
async def export_services_csv():
    """Export IT services as CSV."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM it_services ORDER BY kategorie, description").fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB not available: {e}")
    finally:
        conn.close()

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Description",
            "Provider",
            "Category",
            "Cost (EUR)",
            "Interval",
            "Contract start",
            "Contract end",
            "Notice period",
            "DPA present",
            "DPA date",
            "Contact",
            "Note",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r["description"],
                r["provider"] or "",
                r["kategorie"] or "",
                f"{r['kosten']:.2f}" if r["kosten"] is not None else "",
                r["kosten_intervall"] or "",
                r["vertrag_beginn"] or "",
                r["vertrag_ende"] or "",
                r["kuendigungsfrist"] or "",
                "Yes" if r["avv_present"] else "No",
                r["avv_date"] or "",
                r["kontakt"] or "",
                r["note"] or "",
            ]
        )
    filename = f"services-{datetime.now().strftime('%Y%m%d')}.csv"
    return PlainTextResponse(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _validate_service_body(body: dict) -> dict:
    """Shared validation for POST and PATCH."""
    kategorie = body.get("kategorie", "Others")
    if kategorie not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    intervall = body.get("kosten_intervall", "monthly")
    if intervall not in VALID_INTERVALLE:
        raise HTTPException(status_code=400, detail="Invalid interval")
    kosten = body.get("kosten")
    if kosten is not None:
        try:
            kosten = float(kosten)
            if kosten < 0:
                raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid cost value")
    return {
        "description": (body.get("description") or "").strip(),
        "provider": body.get("provider") or None,
        "kategorie": kategorie,
        "kosten": kosten,
        "kosten_intervall": intervall,
        "vertrag_beginn": body.get("vertrag_beginn") or None,
        "vertrag_ende": body.get("vertrag_ende") or None,
        "kuendigungsfrist": body.get("kuendigungsfrist") or None,
        "avv_present": 1 if body.get("avv_present") else 0,
        "avv_date": body.get("avv_date") or None,
        "kontakt": body.get("kontakt") or None,
        "note": body.get("note") or None,
    }


@app.post("/api/services", status_code=201)
async def api_create_service(request: Request):
    """Create new IT service."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    data = _validate_service_body(body)
    if not data["description"]:
        raise HTTPException(status_code=400, detail="Description is required")
    data["created_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO it_services
               (description, provider, kategorie, kosten, kosten_intervall,
                vertrag_beginn, vertrag_ende, kuendigungsfrist,
                avv_present, avv_date, kontakt, note, created_at)
               VALUES (:description, :provider, :kategorie, :kosten, :kosten_intervall,
                       :vertrag_beginn, :vertrag_ende, :kuendigungsfrist,
                       :avv_present, :avv_date, :kontakt, :note, :created_at)""",
            data,
        )
        conn.commit()
        return {"status": "ok", "id": cur.lastrowid}
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()


@app.patch("/api/service/{service_id}")
async def api_patch_service(request: Request, service_id: int):
    """Update IT service."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    data = _validate_service_body(body)
    if not data["description"]:
        raise HTTPException(status_code=400, detail="Description is required")

    set_clause = ", ".join(f"{k} = :{k}" for k in data)
    data["_id"] = service_id

    conn = get_db()
    try:
        cur = conn.execute(f"UPDATE it_services SET {set_clause} WHERE id = :_id", data)
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Service not found")
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()
    return {"status": "ok"}


@app.delete("/api/service/{service_id}")
async def api_delete_service(service_id: int):
    """Delete IT service."""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM it_services WHERE id = ?", (service_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Service not found")
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"DB-Error: {e}")
    finally:
        conn.close()
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8004, reload=False)
