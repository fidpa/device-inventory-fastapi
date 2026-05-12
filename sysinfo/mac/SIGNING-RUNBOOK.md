# Device Collector — Signing Runbook (Developers)

Step-by-step guide to building, signing, and notarizing `DeviceCollector.app`.
Tested on macOS 14 (Sonoma) and 15 (Sequoia), Apple Silicon.

## TL;DR

Build the binary with PyInstaller → sign with Developer ID (requires GUI session) → assemble the `.app` bundle → sign → notarize → staple → `spctl: accepted`.

## Prerequisites

```bash
# Xcode Command Line Tools
xcode-select -p
# → /Applications/Xcode.app/Contents/Developer

# PyInstaller
pyinstaller --version
# If missing: pip3 install pyinstaller --break-system-packages

# Developer ID certificate
security find-identity -v -p codesigning | grep "Developer ID Application"
# → Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)
```

## Step 1 — Build the binary

```bash
cd /path/to/repo

rm -rf build dist DeviceCollector.spec

pyinstaller \
  --onefile \
  --name "DeviceCollector" \
  collect-sysinfo.py
```

**Result**: `dist/DeviceCollector` (~8 MB, arm64).

> ⚠️ `--target-arch universal2` fails because Homebrew Python is arm64-only (no fat binary). The resulting binary runs on Apple Silicon only. For Intel Macs, build separately on an Intel Mac.

## Step 2 — Sign the binary

> ⚠️ **macOS 14+ over SSH = `errSecInternalComponent`**
> `codesign` requires SecurityAgent, which only runs in GUI sessions.
> Keep a Screen Sharing / VNC session open while signing.

```bash
# Unlock the keychain (once per SSH session):
security unlock-keychain -p "MACOS_LOGIN_PASSWORD" ~/Library/Keychains/login.keychain-db

# Grant codesign access to the key:
security set-key-partition-list \
  -S apple-tool:,apple:,codesign: \
  -s \
  -k "MACOS_LOGIN_PASSWORD" \
  -D "Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)" \
  -t private \
  ~/Library/Keychains/login.keychain-db

# Sign the binary:
codesign \
  --sign "Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)" \
  --options runtime \
  --timestamp \
  --force \
  --entitlements entitlements.plist \
  dist/DeviceCollector

# Verify:
codesign --verify --deep --strict --verbose=2 dist/DeviceCollector
# → dist/DeviceCollector: valid on disk
```

## Step 3 — Assemble the .app bundle

```bash
BASE="/path/to/repo/sysinfo/mac"
APP="$BASE/DeviceCollector.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp dist/DeviceCollector "$APP/Contents/Resources/DeviceCollector"
chmod +x "$APP/Contents/Resources/DeviceCollector"
```

`Contents/Info.plist` and `Contents/MacOS/DeviceCollector-launcher` are checked into the repository. When recreating the bundle from scratch:

**`Contents/Info.plist`** — bundle metadata (`CFBundleIdentifier`: `com.example.deviceinventory`).

**`Contents/MacOS/DeviceCollector-launcher`** — must be a **compiled arm64 binary**, not a shell script. Shell scripts as `CFBundleExecutable` lack a Mach-O header → macOS cannot detect the architecture → the **Rosetta dialog appears**.

Launcher source `app_launcher.c`:
```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <mach-o/dyld.h>

int main(void) {
    char exec_path[4096];
    uint32_t size = sizeof(exec_path);
    if (_NSGetExecutablePath(exec_path, &size) != 0) return 1;

    char *macos_dir = dirname(exec_path);
    char resources[4096];
    snprintf(resources, sizeof(resources), "%s/../Resources/DeviceCollector", macos_dir);

    char cmd[8192];
    snprintf(cmd, sizeof(cmd),
        "osascript -e 'tell application \"Terminal\" to activate' "
        "-e 'tell application \"Terminal\" to do script \"%s\"'",
        resources);
    return system(cmd);
}
```

Compile:
```bash
clang -target arm64-apple-macos12 \
  -o "$APP/Contents/MacOS/DeviceCollector-launcher" \
  app_launcher.c
```

## Step 4 — Sign the .app bundle

```bash
codesign \
  --sign "Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)" \
  --options runtime \
  --timestamp \
  --force \
  --deep \
  --entitlements entitlements.plist \
  "$APP"

# Verify:
codesign --verify --deep --strict --verbose=2 "$APP"
# → DeviceCollector.app: valid on disk
```

> `--deep` automatically signs all bundle contents including `Resources/DeviceCollector`.

## Step 5 — Notarize

```bash
ditto -c -k --keepParent "$APP" "$BASE/DeviceCollector-app.zip"

# Using a stored keychain profile (preferred when GUI is active):
xcrun notarytool submit "$BASE/DeviceCollector-app.zip" \
  --keychain-profile "notarytool-profile" \
  --wait

# Alternatively, pass credentials directly (works without keychain write access):
xcrun notarytool submit "$BASE/DeviceCollector-app.zip" \
  --apple-id "<APPLE_ID>" \
  --team-id "<TEAM_ID>" \
  --password "APPLE_APP_PASSWORD" \
  --wait

# Expected output:
#   status: Accepted
```

**Create a keychain profile** (once, requires a GUI session):
```bash
xcrun notarytool store-credentials "notarytool-profile" \
  --apple-id "<APPLE_ID>" \
  --team-id "<TEAM_ID>" \
  --password "APPLE_APP_PASSWORD"
```

Generate an app-specific password at appleid.apple.com → Sign-In and Security → App-Specific Passwords.

## Step 6 — Staple the ticket

```bash
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
# → The validate action worked!

spctl --assess --type execute --verbose "$APP"
# → DeviceCollector.app: accepted
# → source=Notarized Developer ID
```

✅ Stapling works for `.app` bundles (unlike standalone binaries, which return error 73). The ticket is embedded, so the Gatekeeper check works offline.

## Quick Reference: Full Pipeline

```bash
cd /path/to/repo
BASE="sysinfo/mac"
APP="$BASE/DeviceCollector.app"

# 1. Build the binary
rm -rf build dist DeviceCollector.spec
pyinstaller --onefile --name "DeviceCollector" collect-sysinfo.py

# 2. Sign the binary  [VNC/GUI active!]
codesign --sign "Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)" \
  --options runtime --timestamp --force \
  --entitlements entitlements.plist \
  dist/DeviceCollector

# 3. Assemble the bundle
cp dist/DeviceCollector "$APP/Contents/Resources/DeviceCollector"
chmod +x "$APP/Contents/Resources/DeviceCollector"

# 4. Sign the bundle  [VNC/GUI active!]
codesign --sign "Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)" \
  --options runtime --timestamp --force --deep \
  --entitlements entitlements.plist \
  "$APP"

# 5. Notarize
ditto -c -k --keepParent "$APP" "$BASE/DeviceCollector-app.zip"
xcrun notarytool submit "$BASE/DeviceCollector-app.zip" \
  --apple-id "<APPLE_ID>" --team-id "<TEAM_ID>" \
  --password "APP_PASSWORD" --wait

# 6. Staple
xcrun stapler staple "$APP"
spctl --assess --type execute --verbose "$APP"
# → accepted  ✅
```

## Credentials Reference

| Credential | Value |
|------------|-------|
| Apple ID | `<APPLE_ID>` |
| Team ID | `<TEAM_ID>` |
| Certificate | `Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)` |
| Keychain profile | `notarytool-profile` |
| App-specific password | Generate at appleid.apple.com (one-time only, not recoverable) |

## Known Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `errSecInternalComponent` | macOS 14+: SecurityAgent only runs in GUI sessions | Keep Screen Sharing / VNC active |
| `--target-arch universal2` fails | Homebrew Python is arm64-only | Build without the flag (arm64-only) |
| Stapler error 73 | Only stapleable for Bundles/DMG/PKG | Not relevant — `.app` stapling works |
| Keychain profile cannot be stored | Keychain locked (no GUI) | Pass `--apple-id/--team-id/--password` directly |
| `.command` Gatekeeper warning | Shell scripts cannot be notarized | Use `DeviceCollector.app` instead |
| **Rosetta dialog on app launch** | `CFBundleExecutable` is a shell script (no Mach-O header) | Compile the launcher as a C binary (`clang -target arm64-apple-macos12`) |
| **`different Team IDs` / Python fails to load** | PyInstaller bundles Homebrew Python (foreign Team ID); Hardened Runtime blocks it | Use `--entitlements` with `com.apple.security.cs.disable-library-validation` when signing |
| **App translocation (`/AppTranslocation/` in path)** | App launched directly from Downloads (default macOS behaviour) | No action needed — the app still works correctly |

## Related Documentation

- **End-user guide**: `README.md`
- **Python source**: `collect-sysinfo.py`
