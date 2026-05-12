# macOS Sysinfo Collector

Collects macOS system information, saves it as **JSON**, and uploads it to a WebDAV-compatible cloud (Nextcloud, ownCloud, etc.) for automatic import into the inventory database.

## Prerequisites

| Component | Minimum Version | Notes |
|-----------|-----------------|-------|
| macOS | 10.15 (Catalina) | Requires `system_profiler -json` (Catalina+) |
| Python 3 | 3.6+ | Pre-installed at `/usr/bin/python3` since macOS 12.3 |
| curl | any | Pre-installed |

## Running

### Option A: Double-click (recommended for end users)

1. Copy `DeviceCollector.app` to the Mac (e.g. to the Desktop).
2. Double-click `DeviceCollector.app`.
3. A Terminal window opens automatically.
4. Enter your last name and press Enter.
5. Done — no Gatekeeper warning (signed + notarized).

> **Legacy variant (`RUN.command`)**:
> On first launch macOS shows: *"RUN.command cannot be opened"*.
> Workaround: right-click → **Open** → **Open** to confirm.
> (Required only once; subsequent double-clicks work directly.)
> Prefer `DeviceCollector.app` whenever possible.

### Option B: Terminal (for developers)

```bash
cd sysinfo/mac
python3 collect-sysinfo.py
```

## Collected Data

| Section | Fields |
|---------|--------|
| Device | Name, model (e.g. "MacBook Pro 16-inch, M3 Pro"), serial number |
| Operating System | Name (e.g. "macOS 15.3.2"), build, architecture, install date, last reboot |
| CPU | Description (e.g. "Apple M3 Pro"), cores, threads, clock speed (Intel only) |
| RAM | Total size; modules (Intel: real DIMMs, Apple Silicon: Unified Memory) |
| Drives | Model, serial number, size, interface (NVMe/SATA) |
| Partitions | Mount point, filesystem, size, usage |
| GPU | Model, VRAM, current resolution |
| Monitors | Description, manufacturer, serial number |
| Network | Adapter name, MAC, IP, DHCP status |
| Software | All installed apps (name, version, modification date) |

## Output Filename

```
sysinfo_<lastname>_<hostname>_<YYYYMMDD>.json
```

**Example**: `sysinfo_doe_MacBook-Pro_20260402.json`

- Encoding: UTF-8 (no BOM)
- Format: pretty-printed JSON, 2-space indent
- The file is uploaded to the configured WebDAV endpoint; on failure it is saved to the Desktop.

## Files

| File | Purpose |
|------|---------|
| `RUN.command` | Double-click launcher (legacy) |
| `collect-sysinfo.py` | Main collector script |
| `DeviceCollector.spec` | PyInstaller spec to build a standalone `.app` |
| `entitlements.plist` | macOS code-signing entitlements |
| `SIGNING-RUNBOOK.md` | Step-by-step guide to build and notarize the `.app` |

## Distribution Variants

| File | Recommendation |
|------|----------------|
| `DeviceCollector.app` | **Recommended** — signed and notarized app bundle (no Gatekeeper warning) |
| `collect-sysinfo.py` | For developers running the script directly |
| `RUN.command` | Launcher (legacy — triggers a Gatekeeper warning, prefer the `.app`) |

See `SIGNING-RUNBOOK.md` for instructions on building and notarizing the `.app` bundle.
