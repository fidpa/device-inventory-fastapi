#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""
Example Organization - System information collect v1.0.0
Collects macOS system information and stores it as JSON.
Target: Desktop + Nextcloud (cloud.example.com) for DB import (device inventory)
Schema version: 1.0

Requirements: macOS 10.15+, Python 3 (pre-installed), curl
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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
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
    """Null-safe integer conversion."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value: object) -> float | None:
    """Null-safe float conversion."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# -- Data collection ----------------------------------------------------------


def get_hardware_data() -> dict:
    """system_profiler SPHardwareDataType as dict."""
    data = run_json(["system_profiler", "SPHardwareDataType", "-json"])
    if not data:
        return {}
    items = data.get("SPHardwareDataType", [])
    return items[0] if items else {}


def get_device(hw: dict) -> dict:
    hostname = run(["hostname", "-s"]) or None
    model = safe(hw.get("machine_model"))
    serial_number = safe(hw.get("serial_number"))
    architektur = run(["uname", "-m"]) or None

    return {
        "name": hostname,
        "manufacturer": "Apple Inc.",
        "model": model,
        "serial_number": serial_number,
        "system_type": architektur,
    }


def get_operating_system() -> dict:
    produkt_name = run(["sw_vers", "-productName"]) or "macOS"
    version = run(["sw_vers", "-productVersion"]) or None
    build = run(["sw_vers", "-buildVersion"]) or None
    architektur = run(["uname", "-m"]) or None

    os_name = f"{produkt_name} {version}" if version else produkt_name

    # Installation date: birthtime of /var/db/com.apple.xpc.launchd/
    installiert_am = None
    try:
        stat_result = os.stat("/var/db/com.apple.xpc.launchd/")
        birthtime = getattr(stat_result, "st_birthtime", None)
        if birthtime:
            installiert_am = datetime.fromtimestamp(birthtime).strftime("%Y-%m-%d")
    except OSError:
        pass

    # Last Reboot: kern.boottime
    last_restart = None
    boottime_raw = run(["sysctl", "-n", "kern.boottime"])
    # Format: "{ sec = 1743500000, usec = 0 } Mon Apr  1 08:00:00 2026"
    match = re.search(r"sec\s*=\s*(\d+)", boottime_raw)
    if match:
        try:
            ts = int(match.group(1))
            last_restart = datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, OSError):
            pass

    return {
        "name": os_name,
        "version": version,
        "build": build,
        "architektur": architektur,
        "installiert_am": installiert_am,
        "last_restart": last_restart,
    }


def get_cpu(hw: dict) -> dict:
    architektur = run(["uname", "-m"]) or ""
    is_apple_silicon = architektur == "arm64"

    # CPU-Description
    if is_apple_silicon:
        # Apple Silicon: chip_type from SPHardwareDataType
        description = safe(hw.get("chip_type"))
        if not description:
            description = safe(hw.get("cpu_type"))
    else:
        description = run(["sysctl", "-n", "machdep.cpu.brand_string"]) or None

    cores_raw = run(["sysctl", "-n", "hw.physicalcpu"])
    threads_raw = run(["sysctl", "-n", "hw.logicalcpu"])
    cores = safe_int(cores_raw)
    threads = safe_int(threads_raw)

    # Max clock speed: only available on Intel
    max_takt_mhz = None
    if not is_apple_silicon:
        freq_raw = run(["sysctl", "-n", "hw.cpufrequency_max"])
        freq_hz = safe_int(freq_raw)
        if freq_hz and freq_hz > 0:
            max_takt_mhz = round(freq_hz / 1_000_000)

    return {
        "description": description,
        "cores": cores,
        "threads": threads,
        "max_takt_mhz": max_takt_mhz,
    }


def get_ram(hw: dict) -> dict:
    architektur = run(["uname", "-m"]) or ""
    is_apple_silicon = architektur == "arm64"

    # Totalgroesse
    memsize_raw = run(["sysctl", "-n", "hw.memsize"])
    memsize = safe_int(memsize_raw)
    total_gb = round(memsize / 1_073_741_824, 1) if memsize else 0.0

    if is_apple_silicon:
        # Apple Silicon: no physical RAM slot → synthetic module
        module = [
            {
                "kapazitaet_gb": int(round(total_gb)),
                "type": "LPDDR5",
                "speed_mhz": None,
                "manufacturer": "Apple",
                "slot": "Unified Memory",
            }
        ]
    else:
        # Intel Mac: echte DIMM-Slots via system_profiler
        module = []
        mem_data = run_json(["system_profiler", "SPMemoryDataType", "-json"])
        if mem_data:
            items = mem_data.get("SPMemoryDataType", [])
            for item in items:
                banks = item.get("_items", [])
                for bank in banks:
                    kap_str = bank.get("dimm_size", "")
                    # Format: "16 GB" or "8 GB"
                    kap_match = re.search(r"(\d+)", str(kap_str))
                    kap = int(kap_match.group(1)) if kap_match else None

                    geschw_str = bank.get("dimm_speed", "")
                    geschw_match = re.search(r"(\d+)", str(geschw_str))
                    geschw = int(geschw_match.group(1)) if geschw_match else None

                    module.append(
                        {
                            "kapazitaet_gb": kap,
                            "type": safe(bank.get("dimm_type")),
                            "speed_mhz": geschw,
                            "manufacturer": safe(bank.get("dimm_manufacturer")),
                            "slot": safe(bank.get("_name")),
                        }
                    )

    return {
        "total_gb": total_gb,
        "module": module,
    }


def get_laufwerke() -> list:
    laufwerke = []

    for profiler_type in ["SPNVMeDataType", "SPSerialATADataType"]:
        data = run_json(["system_profiler", profiler_type, "-json"])
        if not data:
            continue
        items = data.get(profiler_type, [])
        for controller in items:
            drives = controller.get("_items", [])
            for drive in drives:
                model = safe(drive.get("_name"))
                serial_number = safe(drive.get("device-serial-number")) or safe(
                    drive.get("device_serial-number")
                )

                # Size: "1 TB" or "512,11 GB"
                size_str = str(drive.get("size", "") or "")
                groesse_gb = None
                size_match = re.search(r"([\d,\.]+)\s*(TB|GB|MB)", size_str, re.IGNORECASE)
                if size_match:
                    num = float(size_match.group(1).replace(",", "."))
                    unit = size_match.group(2).upper()
                    if unit == "TB":
                        groesse_gb = round(num * 1024)
                    elif unit == "GB":
                        groesse_gb = round(num)
                    elif unit == "MB":
                        groesse_gb = round(num / 1024)

                schnittstelle = "NVMe" if profiler_type == "SPNVMeDataType" else "SATA"
                medientype = "SSD"

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
    for line in df_output.splitlines()[1:]:  # skip header row
        parts = line.split()
        if len(parts) < 6:
            continue
        filesystem = parts[0]
        # Only echte Laufwerke (kein tmpfs, devfs, map, etc.)
        if not filesystem.startswith("/dev/"):
            continue  # real drives only (no tmpfs, devfs, map, etc.)

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
                "filesystem": None,  # df -k returns kan Filesystem-Type
                "groesse_gb": int(groesse_gb),
                "used_gb": used_gb,
                "used_prozent": int(used_prozent),
            }
        )

    return partitionen


def get_gpu(display_data: dict | list | None) -> list:
    gpus = []
    if not display_data:
        return gpus

    items = display_data.get("SPDisplaysDataType", [])
    for gpu_item in items:
        name = safe(gpu_item.get("sppci_model"))

        # VRAM
        vram_raw = str(gpu_item.get("spdisplays_vram", "") or "")
        vram_gb = None
        vram_match = re.search(r"([\d,\.]+)\s*(GB|MB)", vram_raw, re.IGNORECASE)
        if vram_match:
            num = float(vram_match.group(1).replace(",", "."))
            unit = vram_match.group(2).upper()
            vram_gb = round(num, 1) if unit == "GB" else round(num / 1024, 1)

        # Resolution from attached display
        # spdisplays_resolution (without _) ist on macOS 13+ stabiler; _ als Fallback
        aufloesung = None
        displays = gpu_item.get("spdisplays_ndrvs", [])
        for display in displays:
            res = safe(display.get("spdisplays_resolution")) or safe(
                display.get("_spdisplays_resolution")
            )
            if res:
                # "2560 x 1440 @ 60.00Hz" → "2560x1440"
                res_match = re.search(r"(\d+)\s*[xX×]\s*(\d+)", res)
                if res_match:
                    aufloesung = f"{res_match.group(1)}x{res_match.group(2)}"
                    break

        gpus.append(
            {
                "name": name,
                "vram_gb": vram_gb,
                "treiber_version": None,  # macOS has no separate GPU driver version
                "aufloesung": aufloesung,
            }
        )

    return gpus


def get_monitore(display_data: dict | list | None) -> list:
    monitore = []
    if not display_data:
        return monitore

    items = display_data.get("SPDisplaysDataType", [])
    for gpu_item in items:
        displays = gpu_item.get("spdisplays_ndrvs", [])
        for display in displays:
            # _spdisplays_display-vendor-id returns hex codes (e.g. "0x10ac") —
            # no meaningful manufacturer name available, so None
            description = safe(display.get("_name"))
            serial_number = safe(display.get("_spdisplays_display-serial-number"))

            monitore.append(
                {
                    "manufacturer": None,
                    "description": description,
                    "serial_number": serial_number,
                }
            )

    return monitore


def get_network() -> list:
    network = []

    # networksetup -listallhardwareports for Adapter-Namen and MACs
    ports_output = run(["networksetup", "-listallhardwareports"])
    adapters: list[dict] = []

    current: dict | None = None
    for line in ports_output.splitlines():
        if line.startswith("Hardware Port:"):
            if current:
                adapters.append(current)
            current = {"name": line.split(":", 1)[1].strip(), "device": None, "mac": None}
        elif line.startswith("Device:") and current:
            current["device"] = line.split(":", 1)[1].strip()
        elif line.startswith("Ethernet Address:") and current:
            current["mac"] = line.split(":", 1)[1].strip()
    if current:
        adapters.append(current)

    # IP-Address and DHCP-Status via ifconfig
    ifconfig_output = run(["ifconfig", "-a"])
    # Parsen: Interfaces with IP-Address ermitteln
    interface_ips: dict[str, str] = {}
    current_iface = None
    for line in ifconfig_output.splitlines():
        iface_match = re.match(r"^(\S+):", line)
        if iface_match:
            current_iface = iface_match.group(1)
        elif current_iface and "inet " in line:
            ip_match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", line)
            if ip_match:
                interface_ips[current_iface] = ip_match.group(1)

    for adapter in adapters:
        device = adapter.get("device")
        if not device:
            continue

        ip = interface_ips.get(device)

        # DHCP-Status
        dhcp = False
        if ip:
            dhcp_info = run(["ipconfig", "getpacket", device], timeout=3)
            dhcp = bool(dhcp_info)  # Wenn Paket present → DHCP active

        network.append(
            {
                "adapter": adapter.get("name"),
                "mac": adapter.get("mac"),
                "ip": ip,
                "dhcp": dhcp,
            }
        )

    # Only return adapters with a MAC address
    return [n for n in network if n["mac"] and n["mac"] != "N/A"]


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

    # Prompt for last name
    last_name = ""
    while not last_name:
        last_name = input("  Please enter your last name and press Enter: ").strip()
        if not last_name:
            print("  Input required. Please enter your last name.")

    safe_last_name = re.sub(r"[^\w\-]", "", last_name) or "UNBEKANNT"

    # Filename
    hostname_raw = run(["hostname", "-s"])
    safe_hostname = re.sub(r"[^\w\-]", "", hostname_raw) or "UNBEKANNT"
    file_name = f"sysinfo_{safe_last_name}_{safe_hostname}.json"

    # Desktop-Path
    desktop_dir = Path.home() / "Desktop"
    if not desktop_dir.is_dir():
        desktop_dir = Path.home()
    lokaler_path = desktop_dir / file_name

    print()
    print("  Collecting system information...")
    print("  Please wait a moment.")
    print()

    collected_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Load expensive system_profiler queries once (used multiple times)
    hw = get_hardware_data()
    display_data = run_json(["system_profiler", "SPDisplaysDataType", "-json"])

    sysinfo = {
        "schema_version": "1.0",
        "collected_at": collected_at,
        "collected_by": last_name,
        "device": get_device(hw),
        "operating_system": get_operating_system(),
        "cpu": get_cpu(hw),
        "ram": get_ram(hw),
        "laufwerke": get_laufwerke(),
        "partitionen": get_partitionen(),
        "gpu": get_gpu(display_data),
        "monitore": get_monitore(display_data),
        "network": get_network(),
    }

    # JSON on Desktop save
    try:
        with open(lokaler_path, "w", encoding="utf-8") as f:
            json.dump(sysinfo, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"  ERROR: File konnte not be saved: {e}", file=sys.stderr)
        return 1

    file_groesse_kb = round(lokaler_path.stat().st_size / 1024)

    # Upload after Nextcloud
    upload_ok = upload_to_nextcloud(lokaler_path, file_name)

    # Show result
    print()
    print("  ========================================================")
    print()
    print("  DONE!  System information collected successfully.")
    print()
    print(f"  File:     {file_name}")
    print(f"  Size:     {file_groesse_kb} KB")
    print(f"  Location: {desktop_dir}")

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
        print("  The file is on your Desktop.")

    print()
    print("  ========================================================")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
