#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""
Example Organization - System information collect v1.0.0
Collects Ubuntu/Linux system information and stores it as JSON.
Target: Home directory + Nextcloud (cloud.example.com) for DB import (device inventory)
Schema version: 1.0

Requirements: Ubuntu 20.04+, Python 3.8+, curl, iproute2 (ip), util-linux (lsblk)
Optional (more detail): dmidecode (sudo), pciutils (lspci)

Usage:
  python3 collect-sysinfo.py              # interactive
  python3 collect-sysinfo.py Doe          # last name as argument
  sudo python3 collect-sysinfo.py         # with root: RAM slots + drive serial numbers
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# -- Configuration -----------------------------------------------------------

MAIL_ADRESSE = "admin@example.com"
NEXTCLOUD_URL = "https://cloud.example.com/remote.php/dav/files/sysinfo/inbox"
NEXTCLOUD_USER = "sysinfo"
NEXTCLOUD_PASSWORD = "YOUR_NEXTCLOUD_APP_PASSWORD"

# ----------------------------------------------------------------------------


def run(cmd: list[str], timeout: int = 10) -> str:
    """Run command, return stdout as string. Empty string on error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        return ""


def run_json(cmd: list[str], timeout: int = 30) -> dict | list | None:
    """Run command, parse stdout as JSON. Returns None on error."""
    raw = run(cmd, timeout=timeout)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def safe(value: object) -> str | None:
    """Null-safe string conversion."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def safe_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_file(path: str) -> str | None:
    """Read file, return None on error."""
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


# DMI placeholder values that are semantically empty
_DMI_EMPTY = frozenset(
    {
        "To Be Filled By O.E.M.",
        "Default string",
        "None",
        "Not Specified",
        "Not Present",
        "Unknown",
    }
)


def read_dmi(field: str) -> str | None:
    """Read DMI field from /sys/class/dmi/id/. Returns None when permissions are missing."""
    val = read_file(f"/sys/class/dmi/id/{field}")
    if not val or val in _DMI_EMPTY:
        return None
    return val


# -- Data collection ----------------------------------------------------------


def get_device() -> dict:
    hostname = run(["hostname", "-s"]) or None
    manufacturer = read_dmi("sys_vendor")
    model = read_dmi("product_name")
    serial_number = read_dmi("product_serial")  # often None without root
    architektur = run(["uname", "-m"]) or None

    return {
        "name": hostname,
        "manufacturer": manufacturer,
        "model": model,
        "serial_number": serial_number,
        "system_type": architektur,
    }


def get_operating_system() -> dict:
    # /etc/os-release parsen
    os_release: dict[str, str] = {}
    raw = read_file("/etc/os-release")
    if raw:
        for line in raw.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                os_release[key.strip()] = val.strip().strip('"')

    os_name = os_release.get("PRETTY_NAME") or os_release.get("NAME") or "Linux"
    version = os_release.get("VERSION_ID") or None
    build = run(["uname", "-r"]) or None  # kernel version
    architektur = run(["uname", "-m"]) or None

    # Installation date: oldest meaningful log file
    installiert_am = None
    for candidate in ["/var/log/installer/syslog", "/var/log/installer", "/lost+found"]:
        try:
            mtime = Path(candidate).stat().st_mtime
            installiert_am = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            break
        except OSError:
            continue

    # Last Reboot via uptime -s ("2026-04-01 08:23:00")
    last_restart = None
    uptime_s = run(["uptime", "-s"])
    if uptime_s:
        try:
            dt = datetime.strptime(uptime_s, "%Y-%m-%d %H:%M:%S")
            last_restart = dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

    return {
        "name": os_name,
        "version": version,
        "build": build,
        "architektur": architektur,
        "installiert_am": installiert_am,
        "last_restart": last_restart,
    }


def get_cpu() -> dict:
    description = None
    cores = None
    threads = None
    max_takt_mhz = None

    lscpu_output = run(["lscpu"])
    lscpu: dict[str, str] = {}
    for line in lscpu_output.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            lscpu[key.strip()] = val.strip()

    description = lscpu.get("Model name") or None
    threads = safe_int(lscpu.get("CPU(s)"))
    sockets = safe_int(lscpu.get("Socket(s)")) or 1
    cores_per = safe_int(lscpu.get("Core(s) per socket"))
    if cores_per:
        cores = cores_per * sockets

    max_mhz_raw = lscpu.get("CPU max MHz", "").replace(",", ".")
    freq = safe_float(max_mhz_raw)
    max_takt_mhz = round(freq) if freq else None

    # Fallback Description: /proc/cpuinfo
    if not description:
        cpuinfo = read_file("/proc/cpuinfo") or ""
        for line in cpuinfo.splitlines():
            if line.startswith("model name"):
                description = line.split(":", 1)[1].strip() or None
                break

    return {
        "description": description,
        "cores": cores,
        "threads": threads,
        "max_takt_mhz": max_takt_mhz,
    }


def get_ram() -> dict:
    # Total size from /proc/meminfo
    total_gb = 0.0
    meminfo = read_file("/proc/meminfo") or ""
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            m = re.search(r"(\d+)", line)
            if m:
                total_gb = round(int(m.group(1)) / 1_048_576, 1)
            break

    # DIMM modules via dmidecode (requires root — empty list without root)
    module: list[dict] = []
    dmi_raw = run(["dmidecode", "-t", "memory"], timeout=10)
    if dmi_raw:
        current: dict | None = None
        for line in dmi_raw.splitlines():
            line = line.strip()
            if line == "Memory Device":
                if current and current.get("kapazitaet_gb"):
                    module.append(current)
                current = {
                    "kapazitaet_gb": None,
                    "type": None,
                    "speed_mhz": None,
                    "manufacturer": None,
                    "slot": None,
                }
            elif current is not None:
                if line.startswith("Size:"):
                    val = line.split(":", 1)[1].strip()
                    m = re.search(r"(\d+)\s*(GB|MB)", val, re.IGNORECASE)
                    if m:
                        num, unit = int(m.group(1)), m.group(2).upper()
                        current["kapazitaet_gb"] = num if unit == "GB" else round(num / 1024)
                elif line.startswith("Type:") and "Detail" not in line:
                    val = line.split(":", 1)[1].strip()
                    current["type"] = val if val not in ("Unknown", "") else None
                elif line.startswith("Speed:"):
                    val = line.split(":", 1)[1].strip()
                    m = re.search(r"(\d+)", val)
                    current["speed_mhz"] = int(m.group(1)) if m else None
                elif line.startswith("Manufacturer:"):
                    val = line.split(":", 1)[1].strip()
                    current["manufacturer"] = (
                        val if val not in ("Unknown", "Not Specified", "") else None
                    )
                elif line.startswith("Locator:") and "Bank" not in line:
                    current["slot"] = line.split(":", 1)[1].strip() or None
        if current and current.get("kapazitaet_gb"):
            module.append(current)

    return {
        "total_gb": total_gb,
        "module": module,
    }


def get_laufwerke() -> list:
    laufwerke = []
    data = run_json(
        [
            "lsblk",
            "--json",
            "--output",
            "NAME,MODEL,SERIAL,SIZE,TYPE,TRAN,ROTA",
            "--bytes",
        ]
    )
    if not data:
        return laufwerke

    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue

        model = safe(dev.get("model"))
        serial_number = safe(dev.get("serial"))
        size_bytes = safe_int(dev.get("size"))
        groesse_gb = round(size_bytes / 1_073_741_824) if size_bytes else None

        name = dev.get("name", "")
        tran = (dev.get("tran") or "").upper()
        if "nvme" in name.lower() or tran == "NVME":
            schnittstelle = "NVMe"
        elif tran:
            schnittstelle = tran
        else:
            schnittstelle = "SATA"

        # rota: True/1 = HDD, False/0 = SSD (bool or String je after lsblk-Version)
        rota = dev.get("rota")
        medientype = "HDD" if rota and str(rota) not in ("0", "false", "False") else "SSD"

        laufwerke.append(
            {
                "model": model,
                "serial_number": serial_number,
                "groesse_gb": groesse_gb,
                "schnittstelle": schnittstelle,
                "medientype": medientype,
            }
        )

    return laufwerke


def get_partitionen() -> list:
    """df -k for physische Volumes."""
    partitionen = []
    df_output = run(["df", "-k"])
    for line in df_output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        filesystem = parts[0]
        if not filesystem.startswith("/dev/"):
            continue
        try:
            blocks = int(parts[1])
            used = int(parts[2])
            mountpoint = parts[5]
            groesse_gb = round(blocks * 1024 / 1_073_741_824, 0)
            used_gb = round(used * 1024 / 1_073_741_824, 1)
            used_prozent = round(used / blocks * 100) if blocks > 0 else 0
        except (ValueError, ZeroDivisionError):
            continue

        partitionen.append(
            {
                "laufwerk": mountpoint,
                "filesystem": None,
                "groesse_gb": int(groesse_gb),
                "used_gb": used_gb,
                "used_prozent": int(used_prozent),
            }
        )

    return partitionen


def get_gpu() -> list:
    """GPU-Info via lspci (optional installiert)."""
    gpus = []
    lspci_output = run(["lspci", "-mm"], timeout=10)
    for line in lspci_output.splitlines():
        if not any(k in line for k in ("VGA", "Display", "3D controller")):
            continue
        # Format: "01:00.0" "VGA compatible controller" "NVIDIA Corporation" "GeForce RTX 3080" ...
        parts = re.findall(r'"([^"]*)"', line)
        name = None
        if len(parts) >= 3:
            vendor, device = parts[1].strip(), parts[2].strip()
            name = f"{vendor} {device}".strip() if vendor else device
        elif parts:
            name = parts[-1]
        if name:
            gpus.append(
                {
                    "name": name,
                    "vram_gb": None,  # without root not reliable
                    "treiber_version": None,
                    "aufloesung": None,  # servers typically have no monitor
                }
            )
    return gpus


def get_network() -> list:
    """Network adapters via ip -j addr."""
    network = []
    addr_data = run_json(["ip", "-j", "addr", "show"])
    if not addr_data:
        return network

    # Exclude virtual/internal interfaces
    _SKIP_PREFIX = ("docker", "br-", "veth", "virbr", "tun", "tap", "dummy")

    for iface in addr_data:
        name = iface.get("ifname", "")
        if name == "lo" or any(name.startswith(p) for p in _SKIP_PREFIX):
            continue

        mac = iface.get("address") or None
        if mac == "00:00:00:00:00:00":
            mac = None

        ip = None
        for addr_info in iface.get("addr_info", []):
            if addr_info.get("family") == "inet":
                ip = addr_info.get("local")
                break

        # DHCP status: NetworkManager → systemd-networkd → dhclient lease
        dhcp = False
        nm_out = run(["nmcli", "-g", "ipv4.method", "connection", "show", name], timeout=3)
        if "auto" in nm_out.lower():
            dhcp = True
        elif Path(f"/var/lib/dhcp/dhclient.{name}.leases").exists():
            dhcp = True
        else:
            try:
                leases = os.listdir("/run/systemd/netif/leases/")
                if any(name in f for f in leases):
                    dhcp = True
            except OSError:
                pass

        network.append(
            {
                "adapter": name,
                "mac": mac,
                "ip": ip,
                "dhcp": dhcp,
            }
        )

    return [n for n in network if n["mac"]]


# -- Upload ------------------------------------------------------------------


def upload_to_nextcloud(file_path: str, file_name: str) -> bool:
    """JSON-File via curl after Nextcloud upload."""
    url = f"{NEXTCLOUD_URL}/{file_name}"
    result = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--max-time",
            "60",
            "--user",
            f"{NEXTCLOUD_USER}:{NEXTCLOUD_PASSWORD}",
            "--upload-file",
            file_path,
            url,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


# -- Main program ------------------------------------------------------------


def main() -> int:
    print()
    print("  ========================================================")
    print("     Example Organization - System information")
    print("  ========================================================")
    print()

    # Last name: CLI argument or interactive input
    if len(sys.argv) > 1:
        last_name = sys.argv[1].strip()
    else:
        last_name = ""
        while not last_name:
            last_name = input("  Please enter your last name and press Enter: ").strip()
            if not last_name:
                print("  Input required.")

    safe_last_name = re.sub(r"[^\w\-]", "", last_name) or "UNBEKANNT"

    hostname_raw = run(["hostname", "-s"])
    safe_hostname = re.sub(r"[^\w\-]", "", hostname_raw) or "UNBEKANNT"
    file_name = f"sysinfo_{safe_last_name}_{safe_hostname}.json"

    # Storage path: home directory (servers have no Desktop)
    storage_dir = Path.home()
    lokaler_path = storage_dir / file_name

    print()
    print("  Collecting system information...")
    print("  Please wait a moment.")
    print()

    collected_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    sysinfo = {
        "schema_version": "1.0",
        "collected_at": collected_at,
        "collected_by": last_name,
        "device": get_device(),
        "operating_system": get_operating_system(),
        "cpu": get_cpu(),
        "ram": get_ram(),
        "laufwerke": get_laufwerke(),
        "partitionen": get_partitionen(),
        "gpu": get_gpu(),
        "network": get_network(),
    }

    # JSON save
    try:
        with open(lokaler_path, "w", encoding="utf-8") as f:
            json.dump(sysinfo, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"  ERROR: File konnte not be saved: {e}", file=sys.stderr)
        return 1

    file_groesse_kb = round(lokaler_path.stat().st_size / 1024)
    upload_ok = upload_to_nextcloud(lokaler_path, file_name)

    print()
    print("  ========================================================")
    print()
    print("  DONE!  System information collected successfully.")
    print()
    print(f"  File:     {file_name}")
    print(f"  Size:     {file_groesse_kb} KB")
    print(f"  Location: {storage_dir}")

    if upload_ok:
        print()
        print("  The file was automatically submitted to IT.")
        print("  No further action required.")
    else:
        print()
        print("  Please send the file by e-mail to:")
        print()
        print(f"  {MAIL_ADRESSE}")
        print()
        print("  The file is in your home directory.")

    print()
    print("  ========================================================")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
