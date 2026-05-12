# Database Schema

The database is SQLite (file `db/devices.db`). Schema creation lives in `ensure_db()` in `src/app.py`.

WAL mode and foreign-key enforcement are both enabled.

## Tables overview

```
devices              ── one row per imported sysinfo JSON
printer_scans        ── one row per imported printer-scan JSON
ctr_hosts            ── physical hosts (CPU, RAM, OS)
ctr_vms              ── VMs/containers; FK → ctr_hosts.id
services             ── IT service contracts
import_log           ── audit trail of every import attempt
```

## `devices`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `file` | TEXT UNIQUE | Source filename (e.g. `sysinfo_doe_PC042_20260401.json`) |
| `collected_at` | TEXT | ISO 8601 datetime |
| `collected_by` | TEXT | Last name entered by the user |
| `device_name` | TEXT | Hostname / computer name |
| `device_manufacturer` | TEXT | |
| `device_model` | TEXT | |
| `device_serial_number` | TEXT | |
| `device_type` | TEXT | `desktop`, `notebook`, `thin-client`, `printer`, `unknown` |
| `os_name` | TEXT | e.g. `Windows 11 Pro`, `macOS 15.3.2` |
| `os_version` | TEXT | |
| `os_build` | TEXT | |
| `cpu_name` | TEXT | |
| `cpu_cores` | INTEGER | |
| `ram_total_gb` | REAL | |
| `json_payload` | TEXT | Full raw JSON for re-rendering / future schema changes |
| `inventory_no` | TEXT | Manually-assigned inventory number |
| `vpn` | TEXT | VPN slot (1–64) or free-form identifier |
| `status` | TEXT | `active`, `inactive`, `decommissioning`, `decommissioned`, `storage` |
| `accessories` | TEXT | JSON-encoded accessory list |
| `note` | TEXT | Free-text admin notes |
| `imported_at` | TEXT | ISO 8601, set by importer |
| `issued_to` | TEXT | Recipient name |
| `issued_since` | TEXT | ISO date |
| `location` | TEXT | Free-text room / desk |
| `acquisition_date` | TEXT | ISO date |
| `acquisition_price` | REAL | EUR net |
| `decommissioned_at` | TEXT | ISO date |

Indexes: `device_name`, `status`, `vpn`, `inventory_no`.

## `printer_scans`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `file` | TEXT UNIQUE | Source filename |
| `collected_at` | TEXT | |
| `hostname` | TEXT | Printer queue name or hostname |
| `ip` | TEXT | Discovered via port name |
| `model` | TEXT | From SNMP `sysDescr` |
| `total_pages` | INTEGER | Lifetime page count |
| `mono_pages` | INTEGER | |
| `color_pages` | INTEGER | |
| `toner_levels` | TEXT | JSON-encoded `{black, cyan, magenta, yellow}` |
| `capabilities` | TEXT | JSON-encoded list (`duplex`, `color`, `scanner`) |
| `printer_status` | TEXT | From SNMP `hrPrinterStatus` |
| `json_payload` | TEXT | Full raw JSON |
| `imported_at` | TEXT | |

Indexes: `hostname`, `ip`.

## `ctr_hosts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `hostname` | TEXT NOT NULL | |
| `os` | TEXT | e.g. `Proxmox VE 8`, `Ubuntu 24.04` |
| `cpu_name` | TEXT | |
| `cpu_cores` | INTEGER | |
| `ram_total_gb` | REAL | |
| `note` | TEXT | |

## `ctr_vms`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `host_id` | INTEGER NOT NULL | FK → `ctr_hosts.id` ON DELETE CASCADE |
| `name` | TEXT NOT NULL | |
| `os` | TEXT | |
| `cpu_cores` | INTEGER | |
| `ram_gb` | REAL | |
| `purpose` | TEXT | |
| `note` | TEXT | |

## `services`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `name` | TEXT NOT NULL | |
| `provider` | TEXT | |
| `category` | TEXT | `SaaS`, `Maintenance`, `Telecom`, `Billing`, `Other` |
| `monthly_cost` | REAL | |
| `yearly_cost` | REAL | |
| `notice_period` | TEXT | e.g. `3 months`, `30 days` |
| `contract_term` | TEXT | |
| `contract_start` | TEXT | ISO date |
| `contract_end` | TEXT | ISO date |
| `contact` | TEXT | |
| `note` | TEXT | |

## `import_log`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `kind` | TEXT | `sysinfo` or `printers` |
| `started_at` | TEXT | |
| `ended_at` | TEXT | NULL if still running |
| `total_files` | INTEGER | |
| `new_records` | INTEGER | |
| `updated_records` | INTEGER | |
| `errors` | INTEGER | |
| `error_message` | TEXT | First error encountered |

## Schema migrations

There is no Alembic / Django-style migration framework. New columns are added directly in `ensure_db()` using `ALTER TABLE` with try/except for "duplicate column name" errors:

```python
def ensure_db():
    conn = get_db()
    # Initial CREATE TABLE statements ...

    # Migrations
    for column_def in [
        "ALTER TABLE devices ADD COLUMN acquisition_price REAL",
        "ALTER TABLE devices ADD COLUMN decommissioned_at TEXT",
    ]:
        try:
            conn.execute(column_def)
        except sqlite3.OperationalError:
            pass  # already exists
```

This is fine for the data volumes this app targets. If you need rollbacks or branching schema history, switch to Alembic.

## Backups

Use SQLite's online backup API (no app downtime):

```bash
sqlite3 db/devices.db ".backup /var/backups/inventory-$(date +%Y%m%d).db"
```

Or copy the file directly while `WAL` is checkpointed:

```bash
sqlite3 db/devices.db "PRAGMA wal_checkpoint(FULL)"
cp db/devices.db /var/backups/inventory-$(date +%Y%m%d).db
```
