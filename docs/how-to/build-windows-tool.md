# Build the Windows Collector Distribution

The Windows collector is a pair of plain text files — no compilation required:

- `sysinfo/win/RUN.bat` — entry point (launches PowerShell)
- `sysinfo/win/collect-sysinfo.ps1` — actual collector

Distributing means: zip them, upload to a download URL, share the link.

## One-time encoding setup

PowerShell 5.1 (the default on Windows 10/11) and `cmd.exe` are picky about file encoding:

| File | Required encoding | Why |
|------|-------------------|-----|
| `RUN.bat` | **cp850** (OEM) | `cmd.exe` interprets script files using the OEM code page |
| `collect-sysinfo.ps1` | **UTF-8 with BOM** | PowerShell 5.1 only detects UTF-8 with a BOM; without it, parser errors occur |

If you edit either file in a UTF-8-only editor (like VS Code on Linux), re-set the encoding before distributing:

```bash
python3 - << 'EOF'
BASE = "sysinfo/win"

# .bat → cp850
with open(f"{BASE}/RUN.bat", "r", encoding="utf-8", errors="replace") as f:
    content = f.read()
with open(f"{BASE}/RUN.bat", "wb") as f:
    f.write(content.encode("cp850", errors="replace"))

# .ps1 → UTF-8 with BOM
with open(f"{BASE}/collect-sysinfo.ps1", "r", encoding="utf-8") as f:
    content = f.read().lstrip("﻿")
with open(f"{BASE}/collect-sysinfo.ps1", "wb") as f:
    f.write(b"\xef\xbb\xbf")
    f.write(content.encode("utf-8"))
print("Encodings set")
EOF
```

## Build the distribution ZIP

```bash
cd sysinfo/win
zip -j sysinfo.zip RUN.bat collect-sysinfo.ps1
```

The `-j` flag stores files without their parent path, so end users get a flat folder when they extract.

## Upload to WebDAV

```bash
source ../../.env
curl -u "${NEXTCLOUD_USER}:${NEXTCLOUD_PASSWORD}" \
  -T sysinfo.zip \
  "${NEXTCLOUD_URL}/remote.php/dav/files/${NEXTCLOUD_USER}/sysinfo.zip"
# Expected response: 201 (Created) or 204 (No Content) — both indicate success
```

Then share the download link via the WebDAV server's "Share" feature, or wire up a permanent short URL (e.g. `https://inventory.example.com/download` redirecting to the share).

## End-user experience

```
1. Download sysinfo.zip
2. Extract (right-click → Extract All)
3. Double-click RUN.bat
4. Windows Defender SmartScreen: "Windows protected your PC"
   → Click "More info" → "Run anyway"
5. Enter last name, press Enter
6. ~10 seconds
7. Done
```

The SmartScreen warning is unavoidable for unsigned scripts. Two ways to suppress it:

- **Code-signing certificate** (~$200/year from a CA like DigiCert or Sectigo) — sign the `.bat` and `.ps1`. This removes the warning after Microsoft has accumulated enough reputation for the certificate (a few hundred users running the script).
- **Internal Group Policy** — for managed Windows fleets, push the script via SCCM/Intune as a trusted package and set ExecutionPolicy to `RemoteSigned` or `Bypass` on the target machines.

## Testing the script

Locally on a Windows machine:

```cmd
cd C:\Users\<you>\Desktop\sysinfo
RUN.bat
```

Or directly in PowerShell (faster iteration during development):

```powershell
cd C:\Users\<you>\Desktop\sysinfo
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\collect-sysinfo.ps1
```

Check the output JSON appears on the user's Desktop (fallback) or that it was uploaded to the WebDAV inbox (success path).

## Customizing

Common tweaks in `collect-sysinfo.ps1`:

```powershell
# Reduce CIM query timeout (default: 30s)
$CIM_TIMEOUT_SECONDS = 10

# Skip software inventory (faster on slow machines)
$COLLECT_SOFTWARE = $false

# Custom upload URL
$NEXTCLOUD_URL = "https://your-server.example.com"
```

After changes, rebuild the ZIP and re-upload. The download link stays the same; users who run an outdated copy from their Desktop will simply continue to use the old version.
