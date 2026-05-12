# Deploy with systemd + nginx

Production deployment recipe for a single Ubuntu/Debian server. Assumes you have root access and a domain pointed at the server.

## Overview

Three systemd units, one nginx site, one TLS certificate:

```
nginx (443) ──► uvicorn (127.0.0.1:8004) ──► SQLite (db/devices.db)
                                          ▲
                       systemd timer ──────┘ (hourly import_sysinfo.py)
                       systemd timer ──────┘ (daily import_printers.py)
```

## Step 1 — Install on the server

```bash
sudo mkdir -p /opt/device-inventory
sudo chown $USER:$USER /opt/device-inventory
git clone https://github.com/fidpa/device-inventory-fastapi /opt/device-inventory
cd /opt/device-inventory

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Step 2 — Create the service user

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin device-inventory
sudo chown -R device-inventory:device-inventory /opt/device-inventory
```

## Step 3 — Configure environment

```bash
sudo cp .env.example /opt/device-inventory/.env
sudo chown device-inventory:device-inventory /opt/device-inventory/.env
sudo chmod 600 /opt/device-inventory/.env
sudo -u device-inventory $EDITOR /opt/device-inventory/.env
# Set NEXTCLOUD_*, AUTH_PASSWORD_HASH, AUTH_SECRET (see tutorial/01-quickstart.md)
```

## Step 4 — Install systemd units

```bash
sudo cp setup/systemd/*.service /etc/systemd/system/
sudo cp setup/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable --now device-inventory.service
sudo systemctl enable --now device-inventory-import.timer
sudo systemctl enable --now device-inventory-import-printers.timer

sudo systemctl status device-inventory.service
# Should show: active (running)
```

The application now listens on `127.0.0.1:8004`.

## Step 5 — nginx reverse proxy

```bash
sudo cp setup/nginx/inventory.example.com.conf.example /etc/nginx/sites-available/inventory.conf
sudo $EDITOR /etc/nginx/sites-available/inventory.conf
# Replace 'inventory.example.com' with your real domain
# Update SSL certificate paths if you don't use Let's Encrypt's default location

sudo ln -s /etc/nginx/sites-available/inventory.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Step 6 — TLS with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d inventory.example.com
```

Certbot will detect the nginx site, request a certificate, and reload nginx automatically.

## Step 7 — Verify

```bash
curl -I https://inventory.example.com/health
# HTTP/2 200
# content-type: text/plain; charset=utf-8

journalctl -u device-inventory.service -n 50
# Should show: "Application startup complete." and "Database ready:"
```

Open `https://inventory.example.com` in a browser → log in.

## Operations

### Restarting the app

```bash
sudo systemctl restart device-inventory.service
```

### Manually running an import

```bash
sudo -u device-inventory /opt/device-inventory/venv/bin/python /opt/device-inventory/scripts/import_sysinfo.py
sudo -u device-inventory /opt/device-inventory/venv/bin/python /opt/device-inventory/scripts/import_printers.py
```

### Checking timer schedules

```bash
sudo systemctl list-timers | grep device-inventory
```

### Backing up the database

```bash
# Online backup (no app restart needed)
sudo -u device-inventory sqlite3 /opt/device-inventory/db/devices.db ".backup /tmp/inventory-backup.db"
sudo cp /tmp/inventory-backup.db /var/backups/inventory-$(date +%Y%m%d).db
sudo gzip /var/backups/inventory-$(date +%Y%m%d).db
```

### Updating

```bash
cd /opt/device-inventory
sudo -u device-inventory git pull
sudo -u device-inventory venv/bin/pip install -U -r requirements.txt
sudo systemctl restart device-inventory.service
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| 502 Bad Gateway | uvicorn not running | `journalctl -u device-inventory.service -n 50` |
| 401 on every request | `AUTH_SECRET` empty or too short | Regenerate (32+ bytes) and restart |
| Login always fails | `AUTH_PASSWORD_HASH` wrong format | Re-run the bcrypt command from the tutorial |
| Import shows 0 new files | WebDAV credentials or path wrong | `curl -u USER:PASS https://cloud.example.com/remote.php/dav/files/USER/inbox/` |
| Database locked | Concurrent writes from import script | Reduce timer frequency or move to PostgreSQL |
