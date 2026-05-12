#!/bin/bash
# Device Inventory - System information collector (macOS)
# Double-clicking in Finder opens this script in Terminal.

cd "$(dirname "$0")"
./DeviceCollector
echo ""
read -rp "Press Enter to exit..."
