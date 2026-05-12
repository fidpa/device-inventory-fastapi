# Quick Start

This tutorial walks you through getting `device-inventory-fastapi` running locally on your machine. By the end you'll have:

- The application running on `http://127.0.0.1:8004`
- A login that works
- A WebDAV connection configured (or stubbed) so you understand the import flow
- One device inventoried

Estimated time: **15 minutes**.

## Prerequisites

- Python 3.10+ (`python3 --version`)
- `git`
- A WebDAV server you can write to (Nextcloud, ownCloud, Seafile). For this tutorial you can use any account.

## Step 1 — Clone and install

```bash
git clone https://github.com/fidpa/device-inventory-fastapi
cd device-inventory-fastapi

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

## Step 2 — Generate authentication credentials

The application uses two secrets:

- `AUTH_PASSWORD_HASH` — a bcrypt hash of your login password.
- `AUTH_SECRET` — a random key used to sign session cookies (HMAC).

Generate both:

```bash
# Pick a password you'll remember
python3 -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD_HERE', bcrypt.gensalt(12)).decode())"
# → copy the $2b$12$... output

python3 -c "import secrets; print(secrets.token_hex(32))"
# → copy the 64-char hex output
```

## Step 3 — Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```ini
NEXTCLOUD_URL=https://cloud.example.com
NEXTCLOUD_USER=your-webdav-account
NEXTCLOUD_PASSWORD=your-webdav-app-password
NEXTCLOUD_PATH=/remote.php/dav/files/your-webdav-account/inbox

AUTH_PASSWORD_HASH=$2b$12$...the-hash-from-step-2...
AUTH_SECRET=...the-64-hex-chars-from-step-2...
```

> **Tip**: Use an app-specific password, not your main account password. Most WebDAV providers offer this in their security settings.

## Step 4 — Run the app

```bash
python3 -m uvicorn src.app:app --host 127.0.0.1 --port 8004
```

You should see:

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Database ready: /path/to/db/devices.db
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8004
```

## Step 5 — Log in

Open `http://127.0.0.1:8004` in your browser. You'll be redirected to `/login`.

Enter the password you used in Step 2. You should land on the empty device list.

## Step 6 — Collect your first device

Pick a platform and run the matching collector:

### macOS / Linux

```bash
cd sysinfo/mac    # or sysinfo/linux
python3 collect-sysinfo.py
```

Enter your last name when prompted. The script writes a JSON file and uploads it to your WebDAV `inbox/` folder.

### Windows

Open `sysinfo/win/` in Explorer, double-click `RUN.bat`, enter your last name when prompted.

## Step 7 — Import the JSON

In the web UI, click **"Run import"** (or run from the command line):

```bash
python3 scripts/import_sysinfo.py
```

Refresh the browser — your device should now appear in the list.

## What's next?

- **Production deployment**: see [`docs/how-to/deploy-systemd.md`](../how-to/deploy-systemd.md)
- **API reference**: see [`docs/reference/api-endpoints.md`](../reference/api-endpoints.md)
- **Why this architecture**: see [`docs/explanation/why-fastapi-monolith.md`](../explanation/why-fastapi-monolith.md)
