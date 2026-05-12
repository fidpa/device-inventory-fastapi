#!/bin/bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
# Device Inventory — Server Setup
# Run once from the installation directory (e.g. /opt/device-inventory/).
#
# Prerequisites:
#   - All files are present in /opt/device-inventory/
#   - sudo rights available
#   - nginx installed
#   - python3-venv installed  (sudo apt install python3-venv)
#   - .env file exists (copy from .env.example and fill in values)

set -euo pipefail
DEVICES_DIR="/opt/device-inventory"

# .env verify
if [[ ! -f "$DEVICES_DIR/.env" ]]; then
    echo "ERROR: $DEVICES_DIR/.env not found"
    echo "Please .env.example copy to .env and fill in:"
    echo "  cp $DEVICES_DIR/.env.example $DEVICES_DIR/.env"
    echo "  nano $DEVICES_DIR/.env"
    exit 1
fi

echo "=== 1. Database-Directory ==="
mkdir -p "$DEVICES_DIR/db"
echo "    OK"

echo "=== 2. Venv + Python-dependencies ==="
python3 -m venv "$DEVICES_DIR/venv"
"$DEVICES_DIR/venv/bin/pip" install --quiet --upgrade pip
"$DEVICES_DIR/venv/bin/pip" install --quiet -r "$DEVICES_DIR/requirements.txt"
echo "    OK"

echo "=== 3. Systemd-Service ==="
sudo cp "$DEVICES_DIR/setup/systemd/device-inventory.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now device-inventory
sudo systemctl status device-inventory --no-pager -l
echo "    OK"

echo "=== 4. Systemd-Timer (automatic Import) ==="
sudo cp "$DEVICES_DIR/setup/systemd/device-inventory-import.service" /etc/systemd/system/
sudo cp "$DEVICES_DIR/setup/systemd/device-inventory-import.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now device-inventory-import.timer
sudo systemctl status device-inventory-import.timer --no-pager -l
echo "    OK (running three times daily: 06:00, 12:00, 18:00)"

echo "=== 5. nginx-Site ==="
NGINX_EXAMPLE="$DEVICES_DIR/setup/nginx/inventory.example.com.conf.example"
NGINX_TARGET="/etc/nginx/sites-available/device-inventory.conf"
if [[ ! -f "$NGINX_TARGET" ]]; then
    echo "    Copying nginx example config to $NGINX_TARGET"
    echo "    Edit the server_name and certificate paths before reloading nginx."
    sudo cp "$NGINX_EXAMPLE" "$NGINX_TARGET"
    sudo ln -sf "$NGINX_TARGET" /etc/nginx/sites-enabled/device-inventory.conf
    echo "    Skipping nginx reload — edit $NGINX_TARGET first, then run:"
    echo "      sudo nginx -t && sudo systemctl reload nginx"
else
    sudo nginx -t
    sudo systemctl reload nginx
    echo "    OK"
fi

echo ""

echo ""
echo "=== Quick test ==="
sleep 2
if curl -sf "http://127.0.0.1:8004/health" > /dev/null; then
    echo "    ✓ Health-Check OK"
else
    echo "    ✗ Health-Check failed"
    sudo systemctl status device-inventory --no-pager
    exit 1
fi

echo ""
echo "=== Next steps ==="
echo "1. Run first import: python3 $DEVICES_DIR/scripts/import_sysinfo.py"
echo "2. Edit nginx config: sudo nano /etc/nginx/sites-available/device-inventory.conf"
echo "   (set server_name to your domain, then: sudo nginx -t && sudo systemctl reload nginx)"
echo "3. Request TLS certificate (Let's Encrypt):"
echo "   sudo certbot --nginx -d your.domain.example.com"
echo ""
echo "App running on http://127.0.0.1:8004"
