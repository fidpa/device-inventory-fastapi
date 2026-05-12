# CLI Tools

Two import scripts live in `scripts/` and are run on a systemd timer (or manually for testing).

## `scripts/import_sysinfo.py`

Imports device sysinfo JSON files from the WebDAV inbox into the SQLite `devices` table.

### Usage

```bash
# Run once (production: triggered by device-inventory-import.timer)
python3 scripts/import_sysinfo.py

# Dry run (lists files but doesn't write to DB)
python3 scripts/import_sysinfo.py --dry-run

# Verbose
python3 scripts/import_sysinfo.py --verbose
```

### Behaviour

1. Reads `.env` for `NEXTCLOUD_URL`, `NEXTCLOUD_USER`, `NEXTCLOUD_PASSWORD`, `NEXTCLOUD_PATH`.
2. Connects to the SQLite database (`db/devices.db`).
3. Sends a `PROPFIND` to the WebDAV inbox path; parses the XML response.
4. For each `*.json` filename not already in the `devices` table:
   - Downloads the file via HTTP GET.
   - Parses the JSON (must conform to the schema documented in `sysinfo/win/README.md`).
   - Inserts a row in `devices` with `imported_at = now()`.
5. Records an entry in `import_log` with totals.
6. Exits 0 on success, non-zero if any file failed.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All files imported (or no new files) |
| `1` | At least one file failed (other files may have succeeded) |
| `2` | WebDAV credentials missing or invalid |

## `scripts/import_printers.py`

Imports printer-scan JSON files. Same overall flow as `import_sysinfo.py` but writes to the `printer_scans` table.

### Usage

```bash
python3 scripts/import_printers.py [--dry-run] [--verbose]
```

### Differences from `import_sysinfo.py`

- Reads from a separate inbox subfolder (`<NEXTCLOUD_PATH>/printers/`).
- Scans containing the same `hostname` are deduplicated — only the most recent scan per hostname is kept.
- Toner levels are normalized: SNMP returns the raw integer level and the maximum capacity; the script computes the percentage and stores both.

## Scheduled execution

The systemd timers run these scripts on a schedule:

- `device-inventory-import.timer` — every hour, 6:00–18:00 (working hours)
- `device-inventory-import-printers.timer` — daily at 06:00

Edit the `.timer` files to change the schedule:

```ini
# Example: every 30 minutes
[Timer]
OnUnitActiveSec=30min
Unit=device-inventory-import.service
```

After changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart device-inventory-import.timer
```

## Manual triggering

From the web UI: log in → click **"Run import"** on the device list page.

From the command line:

```bash
sudo systemctl start device-inventory-import.service
# or directly:
sudo -u device-inventory /opt/device-inventory/venv/bin/python \
     /opt/device-inventory/scripts/import_sysinfo.py
```

Watch the logs:

```bash
journalctl -u device-inventory-import.service -f
```
