# Data Collection Model

How a device's hardware spec gets from "double-click on Windows" to "row in SQLite".

## The pipeline

```
[end-user client]                  [WebDAV server]                    [server]
     │                                  │                                │
     │ collect-sysinfo.{ps1,py}         │                                │
     │ ┌─────────────────┐              │                                │
     │ │ CIM / system_   │              │                                │
     │ │ profiler / lshw │              │                                │
     │ └────────┬────────┘              │                                │
     │          │ JSON                  │                                │
     │ ┌────────▼────────┐              │                                │
     │ │ HTTP PUT        │──────────────┼──► /sysinfo/inbox/<file>.json │
     │ │ (WebDAV)        │              │                                │
     │ └─────────────────┘              │                                │
     │ on failure:                      │                                │
     │   write to ~/Desktop/            │                                │
     │                                  │                                │
                                        │                                │
                                        │ ◄─── PROPFIND (list)           │
                                        │ ◄─── GET <file>.json (download)│
                                        │                                │
                                        │                       ┌────────▼────────┐
                                        │                       │ import_sysinfo  │
                                        │                       │ .py             │
                                        │                       │  ↓              │
                                        │                       │ INSERT/UPDATE   │
                                        │                       │ devices table   │
                                        │                       └─────────────────┘
```

## Why this shape

The pipeline has three **stable interfaces**:

1. The **JSON schema** between collector and server.
2. **WebDAV** between client and storage.
3. **systemd timer** between storage and database.

Each stage can be replaced independently.

### JSON, not direct DB writes

The collector writes JSON to disk, then uploads. It does **not** talk to the FastAPI application directly. This is on purpose:

- **Schema decoupling**: when we add new fields to the database, old collectors keep working. New collectors can include extra fields; importers ignore unknown ones.
- **Offline-first**: the collector works without network access. Failed uploads are saved to the user's Desktop and emailed manually — no data loss.
- **Auditability**: every JSON file is a permanent record of what was on the device at that moment. We can re-import after a schema migration.
- **No client credentials**: the collector knows the WebDAV password (an _app-specific_ one with no other privileges), but never the application's admin password or session secret.

### WebDAV as a queue

The WebDAV inbox acts as a simple message queue:

- **Producers**: the collector scripts (write JSON files).
- **Consumer**: the import script (deletes nothing — see below).
- **Persistence**: as long as the WebDAV server is alive, the messages survive.

Why not Redis / RabbitMQ / Kafka? Because:

- The volume is _trivial_ — dozens of files per week, not per second.
- WebDAV is already needed for software distribution (downloading the collector to end users), so we're not adding a new system.
- Operators already understand WebDAV. They don't need to learn `redis-cli`.

### Files are not auto-deleted

After a successful import, the JSON file **stays in the WebDAV inbox**. The admin UI lets you delete files manually after the corresponding device is decommissioned. This is intentional:

- If the database is corrupted or rebuilt, you can re-run the importer and recover everything.
- Audit trails: who collected what, when.
- Disaster recovery: the inbox doubles as a backup.

The trade-off is storage growth. For 200 devices collecting once a year (~1 KB JSON each), that's 200 KB/year — negligible.

### Why not push from the server side?

Could the importer poll devices directly? In principle yes, but:

- Most clients are behind NAT (laptops, home offices). The server can't reach them.
- Many clients don't have SSH/WinRM/SNMP enabled outbound, and pushing them is invasive.
- A pull-based model means the user is in control: nothing happens without them running the script. That matches the operational reality (small org, no IT-managed laptop fleet).

### Why systemd timer, not cron?

systemd timers integrate with the rest of the systemd ecosystem:

- `journalctl -u device-inventory-import.service` for logs.
- `systemctl list-timers` to see schedules.
- Failed runs get systemd's retry/restart semantics.
- Cron's email-on-failure is awkward; systemd's `OnFailure=` is cleaner.

If you don't have systemd (e.g. on FreeBSD), a cron entry works too:

```
0 6,12,18 * * * cd /opt/device-inventory && venv/bin/python scripts/import_sysinfo.py
```

## Schema versioning

Every collected JSON has a `schema_version` field at the top level:

```json
{
  "schema_version": "1.0",
  "collected_at": "2026-04-01T14:30:00",
  "device": { ... }
}
```

The importer reads `schema_version` and dispatches to the appropriate parser. Currently only `1.0` exists, but the field is there so we can add `1.1` (more fields) or `2.0` (breaking change) without ambiguity.

Backwards compatibility rule: **importers must read all older schemas, but they only need to write the latest**. So a 1.1 importer reads both 1.0 and 1.1 JSONs. A 2.0 importer might choose to drop 1.0 support, after enough time has passed.

## Failure modes

| Stage | Failure | Recovery |
|-------|---------|----------|
| Collection (CIM/system_profiler errors) | Field is set to `null` in JSON, error logged to stderr | Operator sees `—` in the UI; can re-collect |
| Upload (network error, auth fail) | JSON saved to `~/Desktop/`; user emails it | Operator manually drops the file in WebDAV inbox |
| Storage (WebDAV server down) | Same as upload failure | Files accumulate on user Desktops until inbox is reachable |
| Import (JSON parse error) | Logged to `import_log` table with the filename | Operator inspects the file; either fixes it or skips it |
| Import (DB write error) | Transaction rolls back, error logged | Operator investigates; usually disk full or permissions |
| Import (script crash) | systemd records exit code; `OnFailure=` can email an alert | Operator reads journal, runs manually |

The whole pipeline is **idempotent**: re-running the importer over already-imported files is a no-op (filename uniqueness on the `devices` table prevents duplicates).
