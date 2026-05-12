# Build the macOS .app Bundle

The macOS collector ships as a Python script (`sysinfo/mac/collect-sysinfo.py`) that runs out of the box. For end users it's much smoother as a signed and notarized `.app` bundle — no Gatekeeper warnings, double-click to run.

The full build/sign/notarize pipeline is documented in [`sysinfo/mac/SIGNING-RUNBOOK.md`](../../sysinfo/mac/SIGNING-RUNBOOK.md). This page is a high-level guide.

## When to build the .app

You need to rebuild the bundle when:

- The Python collector source changes.
- The `entitlements.plist` changes.
- A new macOS major version invalidates the signature.

For internal development, just running the `.py` directly is fine — only build the `.app` for distribution.

## Prerequisites

| Component | Notes |
|-----------|-------|
| macOS | 10.15+; build on Apple Silicon for arm64, on Intel for x86_64 |
| Xcode CLT | `xcode-select --install` |
| PyInstaller | `pip3 install pyinstaller --break-system-packages` |
| Apple Developer ID | $99/year, paid Apple Developer Program membership |
| App-specific password | Generated at appleid.apple.com |

## Quick build (signed, notarized)

```bash
cd sysinfo/mac
BASE="$(pwd)"
APP="$BASE/DeviceCollector.app"

# 1. Build the binary
pyinstaller --onefile --name "DeviceCollector" collect-sysinfo.py

# 2. Sign the binary
codesign \
  --sign "Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)" \
  --options runtime --timestamp --force \
  --entitlements entitlements.plist \
  dist/DeviceCollector

# 3. Assemble the .app bundle
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp dist/DeviceCollector "$APP/Contents/Resources/DeviceCollector"
chmod +x "$APP/Contents/Resources/DeviceCollector"
# (Add Info.plist and the launcher manually — see SIGNING-RUNBOOK.md)

# 4. Sign the .app
codesign \
  --sign "Developer ID Application: <DEVELOPER_NAME> (<TEAM_ID>)" \
  --options runtime --timestamp --force --deep \
  --entitlements entitlements.plist \
  "$APP"

# 5. Notarize
ditto -c -k --keepParent "$APP" "$BASE/DeviceCollector-app.zip"
xcrun notarytool submit "$BASE/DeviceCollector-app.zip" \
  --apple-id "<APPLE_ID>" --team-id "<TEAM_ID>" \
  --password "<APP_SPECIFIC_PASSWORD>" --wait

# 6. Staple the ticket
xcrun stapler staple "$APP"
spctl --assess --type execute --verbose "$APP"
# → DeviceCollector.app: accepted
```

## Building unsigned (for internal testing only)

If you don't have an Apple Developer ID:

```bash
pyinstaller --onefile --name "DeviceCollector" collect-sysinfo.py
mkdir -p DeviceCollector.app/Contents/MacOS DeviceCollector.app/Contents/Resources
cp dist/DeviceCollector DeviceCollector.app/Contents/Resources/
# Skip steps 2, 4, 5, 6 above
```

End users will see "macOS cannot verify the developer" on first launch. They have to right-click → Open → Open to bypass it. Not user-friendly, but works for internal demos.

## Distribution

After building:

1. ZIP the `.app`: `ditto -c -k --keepParent DeviceCollector.app DeviceCollector-app.zip`
2. Upload to the WebDAV server's distribution folder.
3. Share the download link with end users via your usual channel.

## Troubleshooting

For the full troubleshooting matrix (Rosetta dialogs, Hardened Runtime issues, keychain permissions, App Translocation), see [`sysinfo/mac/SIGNING-RUNBOOK.md`](../../sysinfo/mac/SIGNING-RUNBOOK.md).

The most common stumbling blocks:

| Problem | Quick fix |
|---------|-----------|
| `errSecInternalComponent` over SSH | Keep an active VNC/Screen Sharing session |
| Rosetta dialog on launch | The CFBundleExecutable is a shell script — recompile it as a C binary |
| Library validation blocks Python | Add `disable-library-validation` to `entitlements.plist` |
| Notarization rejects the build | Read the JSON log: `xcrun notarytool log <SUBMISSION_ID> --keychain-profile notarytool-profile` |
