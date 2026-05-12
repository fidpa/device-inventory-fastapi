# Windows Sysinfo Collector

Collects Windows system information via CIM queries, saves it as **JSON**, and uploads it to a WebDAV-compatible cloud (Nextcloud, ownCloud, etc.) for automatic import into the inventory database.

## How It Works

1. End user downloads `sysinfo.zip` from a shared link.
2. User runs `RUN.bat` (which executes `collect-sysinfo.ps1`).
3. PowerShell collects hardware/software details via CIM queries (~5–10 seconds).
4. Output JSON is uploaded via WebDAV; on failure, it falls back to the user's Desktop.
5. Server-side import script (`scripts/import_sysinfo.py`) picks up the JSON and writes to SQLite.

## Files

| File | Purpose |
|------|---------|
| `RUN.bat` | Entry point for end users (launches the PowerShell script) |
| `collect-sysinfo.ps1` | Main logic: CIM queries, JSON output, WebDAV upload |

## End-User Guide

```
1. Download sysinfo.zip from the share link
2. Extract and double-click RUN.bat
3. Windows shows "publisher could not be verified" → click Run
4. Enter your last name → press Enter
5. Wait ~10 seconds → done
```

If the upload fails, the JSON file is saved to the Desktop. The user can manually email it to `admin@example.com`.

## JSON Schema

Filename pattern: `sysinfo_<lastname>_<computername>.json`

```json
{
  "schema_version": "1.0",
  "collected_at": "2026-04-01T14:30:00",
  "collected_by": "Doe",
  "device": {
    "name": "EXAMPLE-PC-001",
    "manufacturer": "Dell Inc.",
    "model": "OptiPlex 7090",
    "serial_number": "ABC1234",
    "system_type": "x64-based PC"
  },
  "operating_system": {
    "name": "Windows 11 Pro",
    "version": "23H2",
    "build": "22631.4890",
    "architecture": "64-bit",
    "installed_at": "2024-03-15",
    "last_reboot": "2026-03-31T08:15:00"
  },
  "cpu": {
    "description": "Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz",
    "cores": 8,
    "threads": 16,
    "max_clock_mhz": 3800
  },
  "ram": {
    "total_gb": 32.0,
    "modules": [
      {
        "capacity_gb": 16,
        "type": "DDR4",
        "speed_mhz": 3200,
        "manufacturer": "Samsung",
        "slot": "DIMM1"
      }
    ]
  },
  "drives": [
    {
      "model": "Samsung SSD 970 EVO Plus 1TB",
      "serial_number": "S4EWNX0R...",
      "size_gb": 953,
      "interface": "NVMe",
      "media_type": "SSD"
    }
  ],
  "partitions": [
    {
      "drive": "C:",
      "filesystem": "NTFS",
      "size_gb": 953,
      "used_gb": 312.4,
      "used_percent": 33
    }
  ],
  "gpu": [
    {
      "name": "NVIDIA GeForce RTX 3060",
      "vram_gb": 12.0,
      "driver_version": "572.83",
      "resolution": "2560x1440"
    }
  ],
  "monitors": [
    {
      "manufacturer": "DEL",
      "description": "DELL U2722D",
      "serial_number": "ABC123"
    }
  ],
  "network": [
    {
      "adapter": "Intel(R) Ethernet Connection I219-LM",
      "mac": "A4:BB:6D:12:34:56",
      "ip": "192.0.2.42",
      "dhcp": true
    }
  ],
  "software": [
    {
      "name": "Microsoft Office Professional Plus 2021",
      "version": "16.0.14332.20706",
      "installed_at": "2024-03-15"
    }
  ]
}
```

**Schema notes**:
- Missing values are emitted as `null` (not `-`), so they are directly DB-compatible.
- `software` contains **all** installed programs (no truncation), sorted alphabetically.
- Date fields use ISO-8601 format (`yyyy-MM-dd` or `yyyy-MM-ddTHH:mm:ss`).
- `schema_version` enables future extensions without breaking existing imports.

## Upload Configuration

| Parameter | Value |
|-----------|-------|
| WebDAV URL | `https://cloud.example.com` |
| Account | `sysinfo` |
| App Password | Read from `.env` (`NEXTCLOUD_APP_PASSWORD`) |
| Upload Path | `/remote.php/dav/files/sysinfo/<filename>` |

The credentials are stored as plaintext inside `collect-sysinfo.ps1` (an **app password**, not a login password). Worst case: an attacker can upload files to the dedicated `sysinfo` account.

## Distributing the Collector

After modifying `RUN.bat` or `collect-sysinfo.ps1`, repackage and re-upload:

```bash
cd sysinfo/win
zip -j sysinfo.zip RUN.bat collect-sysinfo.ps1

curl -u "${NEXTCLOUD_LOGIN}:${NEXTCLOUD_APP_PASSWORD}" \
  -T sysinfo.zip \
  "${NEXTCLOUD_URL}/remote.php/dav/files/${NEXTCLOUD_LOGIN}/sysinfo.zip"
# Expected response: 201 (Created) or 204 (Updated)
```

## Encoding Requirements

| File | Encoding | Reason |
|------|----------|--------|
| `RUN.bat` | **cp850** (OEM) | `cmd.exe` uses the OEM code page; cp1252 displays umlauts incorrectly |
| `collect-sysinfo.ps1` | **UTF-8 with BOM** | PowerShell 5.1 only recognizes UTF-8 with a BOM; without it, parser errors occur |

After editing either file, re-set the encoding:

```bash
python3 - << 'EOF'
BASE = "sysinfo/win"

# .bat -> cp850
with open(f"{BASE}/RUN.bat", "r", encoding="cp850", errors="replace") as f:
    content = f.read()
with open(f"{BASE}/RUN.bat", "wb") as f:
    f.write(content.encode("cp850"))

# .ps1 -> UTF-8 BOM
with open(f"{BASE}/collect-sysinfo.ps1", "r", encoding="utf-8") as f:
    content = f.read().lstrip("﻿")
with open(f"{BASE}/collect-sysinfo.ps1", "wb") as f:
    f.write(b"\xef\xbb\xbf")
    f.write(content.encode("utf-8"))
print("OK")
EOF
```
