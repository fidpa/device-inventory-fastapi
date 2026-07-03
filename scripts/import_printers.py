#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""
import_printers.py — Nextcloud WebDAV → SQLite Import (printer scans)

Reads all printer_*.json files from Nextcloud and imports new entries
into the local SQLite database. Already-imported files are skipped.

Usage:
  python3 scripts/import_printers.py

Configuration via .env (im App-Root):
  NEXTCLOUD_URL       - e.g. https://cloud.example.com
  NEXTCLOUD_USER      - WebDAV-User
  NEXTCLOUD_PASSWORD  - App-Password
  NEXTCLOUD_PATH      - WebDAV-Path, e.g. /remote.php/dav/files/sysinfo
"""

import argparse
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

PRINTER_PATTERN = re.compile(r"^printer_[A-Za-z0-9_\-]+\.json$", re.IGNORECASE)


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
    """PROPFIND on Nextcloud WebDAV → list of all printer_*.json filenames."""
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
        filename = href.rstrip("/").split("/")[-1]
        if PRINTER_PATTERN.match(filename):
            files.append(filename)
    return files


def get_existing_files(conn: sqlite3.Connection) -> set[str]:
    """Already-imported filenames from the DB."""
    try:
        rows = conn.execute("SELECT file FROM printer_scans").fetchall()
        return {r["file"] for r in rows}
    except sqlite3.OperationalError:
        return set()


def download_json(session: requests.Session, filename: str) -> dict:
    """Download and parse JSON file from Nextcloud.
    utf-8-sig: strips UTF-8 BOM written automatically by PowerShell 5.1."""
    url = f"{NEXTCLOUD_URL}{NEXTCLOUD_PATH}/{filename}"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return json.loads(response.content.decode("utf-8-sig"))


def insert_scan(conn: sqlite3.Connection, filename: str, data: dict) -> None:
    """Upsert by hostname: one entry per WTS machine, updated with each new scan."""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    printer = data.get("printer") or []
    hostname = data.get("collected_by")
    json_payload = json.dumps(data, ensure_ascii=False)

    existing = conn.execute(
        "SELECT id FROM printer_scans WHERE hostname = ?", (hostname,)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE printer_scans
               SET file=?, collected_at=?, printer_count=?, json_payload=?, imported_at=?
               WHERE hostname=?""",
            (filename, data.get("collected_at"), len(printer), json_payload, now, hostname),
        )
    else:
        conn.execute(
            """INSERT INTO printer_scans (file, collected_at, hostname, printer_count, json_payload, imported_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (filename, data.get("collected_at"), hostname, len(printer), json_payload, now),
        )


def _finalize_log(
    conn: sqlite3.Connection,
    log_id: int | None,
    new_scans: int,
    error: str | None,
) -> None:
    if log_id is None:
        return
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        conn.execute(
            "UPDATE printer_import_log SET completed_am = ?, new_scans = ?, error = ? WHERE id = ?",
            (now, new_scans, error, log_id),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"WARNING: import log could not be updated: {e}", file=sys.stderr)


def _print_printer_verbose(filename: str, data: dict) -> None:
    """Print one row per printer: name, IP, status, SNMP availability and toner count."""
    printer = data.get("printer") or []
    hostname = data.get("collected_by", "?")
    print(f"  {filename} ({hostname}, {len(printer)} Printers):")
    for d in printer:
        name = d.get("name") or "?"
        ip = d.get("ip_address") or "?"
        status = d.get("status") or "?"
        snmp = d.get("snmp")
        snmp_ok = "SNMP:yes" if snmp else "SNMP:no"
        toner_count = len(snmp.get("toner") or []) if snmp else 0
        print(f"    {name} | {ip} | {status} | {snmp_ok} | {toner_count} Toner")


def _process_single(filename: str, data: dict, dry_run: bool, verbose: bool) -> None:
    """Process a single local JSON file (via --file)."""
    hostname = data.get("collected_by", "?")
    printer = data.get("printer") or []
    if dry_run:
        print(f"[DRY-RUN] {filename}: {hostname}, {len(printer)} printers — no DB insert")
    else:
        print(f"  Importing {filename} ({hostname}, {len(printer)} printers) ...")
    if verbose:
        _print_printer_verbose(filename, data)
    if not dry_run:
        conn = get_db()
        try:
            insert_scan(conn, filename, data)
            conn.commit()
            print(f"  ✓ {filename} imported")
        except Exception as e:
            print(f"  ✗ {filename}: {e}", file=sys.stderr)
            conn.rollback()
            raise
        finally:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Printers-Scans import")
    parser.add_argument("--dry-run", action="store_true", help="No DB insert, no log entry")
    parser.add_argument("--file", metavar="PATH", help="Lokale JSON-File statt Nextcloud")
    parser.add_argument("--verbose", action="store_true", help="Show details per printer")
    args = parser.parse_args()

    # --file: process local file instead of Nextcloud (skip validate_config)
    if args.file:
        try:
            data = json.loads(Path(args.file).read_bytes().decode("utf-8-sig"))
        except Exception as e:
            print(f"ERROR: file could not be read: {e}", file=sys.stderr)
            return 1
        _process_single(Path(args.file).name, data, args.dry_run, args.verbose)
        return 0

    # Normaler Nextcloud-Path
    try:
        validate_config()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    session = requests.Session()
    session.auth = (NEXTCLOUD_USER, NEXTCLOUD_PASSWORD)

    conn = get_db()
    log_id: int | None = None
    imported = 0
    error_msgs: list[str] = []
    fatal_error: str | None = None
    new_files: list[str] = []

    try:
        if not args.dry_run:
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            try:
                cur = conn.execute("INSERT INTO printer_import_log (started_at) VALUES (?)", (now,))
                log_id = cur.lastrowid
                conn.commit()
            except sqlite3.OperationalError:
                pass  # printer_import_log-Table not yet present (Erstlauf)

        prefix = "[DRY-RUN] " if args.dry_run else ""
        print(f"{prefix}Connecting to {NEXTCLOUD_URL}{NEXTCLOUD_PATH} ...")
        try:
            files = list_nextcloud_files(session)
        except requests.RequestException as e:
            fatal_error = str(e)
            print(f"ERROR: Nextcloud not reachable: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            fatal_error = str(e)
            print(f"ERROR: unexpected error retrieving file list: {e}", file=sys.stderr)
            return 1

        print(f"{prefix}Found: {len(files)} printer_*.json files")

        existing = get_existing_files(conn)
        new_files = [f for f in files if f not in existing]
        print(f"{prefix}Already imported: {len(existing)}, New: {len(new_files)}")

        for filename in new_files:
            try:
                data = download_json(session, filename)
                if args.verbose:
                    _print_printer_verbose(filename, data)
                if not args.dry_run:
                    insert_scan(conn, filename, data)
                    conn.commit()
                    imported += 1
                    hostname = data.get("collected_by", "?")
                    count = len(data.get("printer") or [])
                    print(f"  ✓ {filename} ({hostname}, {count} Printers)")
                else:
                    hostname = data.get("collected_by", "?")
                    count = len(data.get("printer") or [])
                    print(f"[DRY-RUN] Would import: {filename} ({hostname}, {count} Printers)")
            except Exception as e:
                error_msgs.append(f"{filename}: {e}")
                print(f"  ✗ {filename}: {e}", file=sys.stderr)
                if not args.dry_run:
                    conn.rollback()

    finally:
        if not args.dry_run:
            error = fatal_error or ("; ".join(error_msgs) if error_msgs else None)
            _finalize_log(conn, log_id, imported, error)
        conn.close()

    if args.dry_run:
        print(f"\n[DRY-RUN] Completed: {len(new_files)} files checked, no DB insert performed")
    else:
        print(f"\nImport completed: {imported} new imported, {len(error_msgs)} error(s)")
    return 1 if error_msgs else 0


if __name__ == "__main__":
    sys.exit(main())
