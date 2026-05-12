# Add SNMP Printer Discovery

The Windows Terminal Server collector (`sysinfo/wts/collect-printers.ps1`) discovers networked printers via two channels:

1. **CIM** — the local Windows printer queue (`Get-CimInstance -ClassName Win32_Printer`)
2. **SNMP** — direct UDP queries to each discovered printer's IP for toner level, page count, capabilities

This guide shows how to configure SNMP collection.

## Prerequisites

- Windows Terminal Server (or any Windows machine with shared printers).
- SNMP enabled on each printer (most enterprise printers — HP, Brother, Lexmark, Kyocera, Canon — have it on by default with the `public` community string).
- Network access from the Windows machine to each printer's IP on UDP/161.

## Step 1 — Verify SNMP works

From the Windows machine, install the `SNMP` Windows feature (or use a portable SNMP tool):

```powershell
# Install SNMP feature
Add-WindowsCapability -Online -Name "SNMP.Client~~~~0.0.1.0"

# Test against one printer
$ip = "192.0.2.42"
$oid = "1.3.6.1.2.1.1.1.0"  # sysDescr — should return printer model name
# Use any SNMP tool, e.g. Get-SnmpData from PSSnmp module
```

## Step 2 — Run the collector

```cmd
cd sysinfo\wts
RUN.bat
```

The script:
1. Lists all printer queues via CIM.
2. For each queue, extracts the IP from the port name (e.g. `IP_192.0.2.42`).
3. Sends SNMP queries to each IP for:
   - Model name (`sysDescr`)
   - Total page count (`prtMarkerLifeCount`)
   - Per-marker page counts (mono / colour)
   - Toner levels (`prtMarkerSuppliesLevel`)
   - Status (`hrPrinterStatus`)
4. Writes a JSON file with one entry per printer.
5. Uploads to the WebDAV inbox.

## Step 3 — Server-side import

The server-side timer picks up new printer scans:

```bash
sudo -u device-inventory /opt/device-inventory/venv/bin/python \
  /opt/device-inventory/scripts/import_printers.py
```

Or wait for `device-inventory-import-printers.timer` to fire (default: daily at 06:00).

## Customizing SNMP behaviour

Edit `sysinfo/wts/collect-printers.ps1`:

### Different community string

Some organizations use `private` or a custom community for read access:

```powershell
$SNMP_COMMUNITY = "your-community-string"
```

### Skip specific printers

```powershell
$SKIP_HOSTNAMES = @("printer-test", "printer-decommissioned")
```

### Custom timeout

Default SNMP timeout is 2 seconds per printer. For slow printers or distant networks:

```powershell
$SNMP_TIMEOUT_MS = 5000
```

## Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| All printers report `null` for SNMP fields | UDP/161 blocked at the firewall | Open the port from the collector to the printer subnet |
| Some printers return errors | SNMP disabled on those printers | Enable in the printer's web UI: Settings → Network → SNMP |
| Page counts are way off | Printer reports cumulative since last service, not lifetime | Document this; it's a printer firmware quirk |
| Toner level shows `-2` or `-3` | Reserved sentinel values defined in RFC 3805 | Map them to "low warning" / "no estimate available" in the UI |

## Reference: relevant SNMP OIDs

| OID | Description |
|-----|-------------|
| `1.3.6.1.2.1.1.1.0` | System description (model name) |
| `1.3.6.1.2.1.1.5.0` | System name (hostname) |
| `1.3.6.1.2.1.43.10.2.1.4.1.1` | Total impressions (lifetime page count) |
| `1.3.6.1.2.1.43.11.1.1.9.1.X` | Toner level (X = supply index) |
| `1.3.6.1.2.1.43.11.1.1.6.1.X` | Toner description (e.g. "Black Toner Cartridge") |
| `1.3.6.1.2.1.25.3.5.1.1.1` | Printer status (1=other, 2=unknown, 3=idle, 4=printing, 5=warmup) |

See [RFC 3805 (Printer MIB)](https://datatracker.ietf.org/doc/html/rfc3805) for the complete OID catalogue.
