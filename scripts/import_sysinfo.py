#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""
import_sysinfo.py — Nextcloud WebDAV → SQLite Import

Reads all sysinfo_*.json files from Nextcloud and imports new entries
into the local SQLite database. Already-imported files are skipped.

Usage:
  python3 scripts/import_sysinfo.py

Configuration via .env (im App-Root):
  NEXTCLOUD_URL       - e.g. https://cloud.example.com
  NEXTCLOUD_USER      - WebDAV-User
  NEXTCLOUD_PASSWORD  - App-Password
  NEXTCLOUD_PATH      - WebDAV-Path, e.g. /remote.php/dav/files/sysinfo
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import requests
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
load_dotenv(APP_DIR / ".env")

NEXTCLOUD_URL = os.getenv("NEXTCLOUD_URL", "").rstrip("/")
NEXTCLOUD_USER = os.getenv("NEXTCLOUD_USER", "")
NEXTCLOUD_PASSWORD = os.getenv("NEXTCLOUD_PASSWORD", "")
NEXTCLOUD_PATH = os.getenv("NEXTCLOUD_PATH", "/remote.php/dav/files/sysinfo")

DB_PATH = APP_DIR / "db" / "devices.db"

SYSINFO_PATTERN = re.compile(r"^sysinfo_.+\.json$", re.IGNORECASE)


def validate_config() -> None:
    """Verifies that all Nextcloud credentials are set in .env."""
    missing = [
        k
        for k, v in {
            "NEXTCLOUD_URL": NEXTCLOUD_URL,
            "NEXTCLOUD_USER": NEXTCLOUD_USER,
            "NEXTCLOUD_PASSWORD": NEXTCLOUD_PASSWORD,
        }.items()
        if not v
    ]
    if missing:
        raise ValueError(
            f"Missing configuration: {', '.join(missing)}\n"
            "Please create a .env file (template: .env.example)"
        )


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Wait on concurrent writes (web app) instead of "database is locked"
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def list_nextcloud_files(session: requests.Session) -> list[str]:
    """PROPFIND on Nextcloud WebDAV → list of all filenames."""
    url = f"{NEXTCLOUD_URL}{NEXTCLOUD_PATH}"
    response = session.request(
        "PROPFIND",
        url,
        headers={"Depth": "1", "Content-Type": "application/xml"},
        data="""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:displayname/></d:prop>
</d:propfind>""",
        timeout=30,
    )
    response.raise_for_status()

    ns = {"d": "DAV:"}
    tree = ElementTree.fromstring(response.content)
    files = []
    for response_elem in tree.findall("d:response", ns):
        href = response_elem.findtext("d:href", namespaces=ns) or ""
        # Extract filenames only (not the directory itself)
        filename = href.rstrip("/").split("/")[-1]
        if SYSINFO_PATTERN.match(filename):
            files.append(filename)
    return files


def get_existing_devices(conn: sqlite3.Connection) -> dict[str, str]:
    """Already-imported devices: {file: collected_at}."""
    rows = conn.execute("SELECT file, collected_at FROM devices").fetchall()
    return {r["file"]: r["collected_at"] for r in rows}


def download_json(session: requests.Session, filename: str) -> dict:
    """Download and parse JSON file from Nextcloud.
    utf-8-sig: strips UTF-8 BOM written automatically by PowerShell 5.1."""
    url = f"{NEXTCLOUD_URL}{NEXTCLOUD_PATH}/{filename}"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return json.loads(response.content.decode("utf-8-sig"))


_THIN_CLIENT_KWS = [
    "thin client",
    "thinclient",
    "t420",
    "t430",
    "t530",
    "t630",
    "t640",
    "t730",
    "t740",
    "wyse",
    "igel",
    "teradici",
]
_NOTEBOOK_KWS = [
    "notebook",
    "laptop",
    "book",
    "latitude",
    "thinkpad",
    "inspiron",
    "vostro",
    "xps",
    "yoga",
    "ideapad",
    "surface",
    "portege",
    "tecra",
    "lifebook",
    "pavilion",
    "envy",
    "spectre",
    "zbook",
]


def _detect_device_type(model: str | None) -> str:
    """Infer device type from model description."""
    if not model:
        return "unknown"
    m = model.lower()
    if any(kw in m for kw in _THIN_CLIENT_KWS):
        return "thin-client"
    if any(kw in m for kw in _NOTEBOOK_KWS):
        return "notebook"
    return "desktop"


def extract_fields(data: dict) -> dict:
    """Extract relevant fields from the JSON payload."""
    device = data.get("device") or {}
    bs = data.get("operating_system") or {}
    cpu = data.get("cpu") or {}
    ram = data.get("ram") or {}

    model = device.get("model")
    return {
        "collected_at": data.get("collected_at"),
        "collected_by": (data.get("collected_by") or "").strip().lower() or None,
        "device_name": device.get("name"),
        "device_manufacturer": device.get("manufacturer"),
        "device_model": model,
        "device_serial_number": device.get("serial_number"),
        "device_type": _detect_device_type(model),
        "os_name": bs.get("name"),
        "os_version": bs.get("version"),
        "os_build": bs.get("build"),
        "cpu_description": cpu.get("description"),
        "cpu_cores": cpu.get("cores"),
        "ram_total_gb": ram.get("total_gb"),
    }


def upsert_device(conn: sqlite3.Connection, filename: str, data: dict, existing: dict) -> str:
    """INSERT new device or UPDATE technical fields for known filename.
    Manual fields (note, status, issued_to, output_since, accessories, vpn) are preserved."""
    fields = extract_fields(data)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    params = {
        "file": filename,
        **fields,
        "json_payload": json.dumps(data, ensure_ascii=False),
        "imported_at": now,
    }

    if filename in existing:
        conn.execute(
            """
            UPDATE devices SET
                collected_at = :collected_at,
                collected_by = :collected_by,
                device_name = :device_name,
                device_manufacturer = :device_manufacturer,
                device_model = :device_model,
                device_serial_number = :device_serial_number,
                device_type = :device_type,
                os_name = :os_name,
                os_version = :os_version,
                os_build = :os_build,
                cpu_description = :cpu_description,
                cpu_cores = :cpu_cores,
                ram_total_gb = :ram_total_gb,
                json_payload = :json_payload,
                imported_at = :imported_at
            WHERE file = :file
            """,
            params,
        )
        return "updated"

    conn.execute(
        """
        INSERT INTO devices (
            file, collected_at, collected_by,
            device_name, device_manufacturer, device_model, device_serial_number,
            device_type,
            os_name, os_version, os_build,
            cpu_description, cpu_cores, ram_total_gb,
            json_payload, imported_at
        ) VALUES (
            :file, :collected_at, :collected_by,
            :device_name, :device_manufacturer, :device_model, :device_serial_number,
            :device_type,
            :os_name, :os_version, :os_build,
            :cpu_description, :cpu_cores, :ram_total_gb,
            :json_payload, :imported_at
        )
        """,
        params,
    )
    return "inserted"


def assign_missing_inventory_numbers(conn: sqlite3.Connection) -> int:
    """Assign the next available IT-XXXX number to devices without an inventory number."""
    without = conn.execute(
        "SELECT id FROM devices WHERE inventory_number IS NULL ORDER BY id"
    ).fetchall()
    if not without:
        return 0
    highest = conn.execute(
        "SELECT inventory_number FROM devices WHERE inventory_number LIKE 'IT-%' ORDER BY inventory_number DESC LIMIT 1"
    ).fetchone()
    next_num = 1
    if highest:
        try:
            next_num = int(highest[0].split("-")[1]) + 1
        except (IndexError, ValueError):
            pass
    assigned = 0
    for (dev_id,) in without:
        nr = f"IT-{next_num:04d}"
        try:
            conn.execute("UPDATE devices SET inventory_number = ? WHERE id = ?", (nr, dev_id))
            next_num += 1
            assigned += 1
        except sqlite3.IntegrityError:
            next_num += 1  # number already taken, skip
    conn.commit()
    return assigned


def _finalize_log(
    conn: sqlite3.Connection,
    log_id: int | None,
    new_devices: int,
    aktualisierte_device: int,
    error: str | None,
) -> None:
    """Close the import log entry."""
    if log_id is None:
        return
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        conn.execute(
            """UPDATE import_log
               SET completed_am = ?, new_devices = ?, aktualisierte_device = ?, error = ?
               WHERE id = ?""",
            (now, new_devices, aktualisierte_device, error, log_id),
        )
        conn.commit()
    except Exception as e:
        print(f"WARNING: import log could not be updated: {e}", file=sys.stderr)


def main() -> int:
    try:
        validate_config()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    session = requests.Session()
    session.auth = (NEXTCLOUD_USER, NEXTCLOUD_PASSWORD)

    conn = get_db()
    log_id: int | None = None
    new = 0
    aktualisiert = 0
    error_msgs: list[str] = []
    fatal_error: str | None = None

    try:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            cur = conn.execute("INSERT INTO import_log (started_at) VALUES (?)", (now,))
            log_id = cur.lastrowid
            conn.commit()
        except Exception:
            pass  # import_log-Table existiert ggf. not yet

        print(f"Connecting to {NEXTCLOUD_URL}{NEXTCLOUD_PATH} ...")
        try:
            files = list_nextcloud_files(session)
        except requests.RequestException as e:
            fatal_error = str(e)
            print(f"ERROR: Nextcloud not reachable: {e}", file=sys.stderr)
            return 1

        print(f"Found: {len(files)} sysinfo_*.json files")

        existing = get_existing_devices(conn)
        new_count = sum(1 for f in files if f not in existing)
        update_count = len(files) - new_count
        print(f"Known: {update_count}, New: {new_count}")

        for filename in files:
            try:
                data = download_json(session, filename)

                # Known file is only updated if the collection date is newer
                if filename in existing:
                    if data.get("collected_at") == existing[filename]:
                        continue  # no change
                    upsert_device(conn, filename, data, existing)
                    conn.commit()
                    aktualisiert += 1
                    device = (data.get("device") or {}).get("name", "?")
                    print(f"  ↻ {filename} ({device}) — updated")
                else:
                    upsert_device(conn, filename, data, existing)
                    conn.commit()
                    new += 1
                    device = (data.get("device") or {}).get("name", "?")
                    print(f"  ✓ {filename} ({device})")
            except Exception as e:
                error_msgs.append(f"{filename}: {e}")
                print(f"  ✗ {filename}: {e}", file=sys.stderr)
                conn.rollback()

    finally:
        assigned = assign_missing_inventory_numbers(conn)
        if assigned:
            print(f"  → {assigned} new inventory number(s) assigned")
        error = fatal_error or ("; ".join(error_msgs) if error_msgs else None)
        _finalize_log(conn, log_id, new, aktualisiert, error)
        conn.close()

    print(f"\nImport completed: {new} new, {aktualisiert} updated, {len(error_msgs)} error(s)")
    return 1 if error_msgs else 0


if __name__ == "__main__":
    sys.exit(main())
