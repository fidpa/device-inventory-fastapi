# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-05-10

### Added
- Initial public release
- FastAPI web application for device inventory management (single-file architecture, ~2k LOC)
- Cross-platform sysinfo collectors:
  - Windows (PowerShell + CIM queries, no admin rights needed)
  - macOS (Python + `system_profiler`, optional signed `.app` bundle)
  - Linux (Python + `lshw` / `dmidecode`)
  - Windows Terminal Server printer collector (CIM + SNMP)
- WebDAV-based data synchronization (works with Nextcloud, ownCloud, Seafile)
- SNMP-based printer discovery with toner-level reporting
- Container / VM (CTR) inventory
- IT services tracker (contracts, providers, costs, notice periods)
- PDF and CSV exports for all sections
- Authentication: bcrypt password hashing + HMAC-signed session cookies
- In-memory login rate limiting (5 attempts / 60 seconds per IP)
- Security headers middleware: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- systemd service + timer units for the FastAPI app and import jobs
- nginx reverse-proxy example configuration
- pytest test suite (auth, routes, PDF export)
- Ruff linting + GitHub Actions CI (lint + tests)
- DIATAXIS-organized documentation (tutorial / how-to / reference / explanation)

### Architecture
- SQLite backend with WAL mode and foreign-key enforcement
- Jinja2 templates + vanilla JavaScript (no frontend build step)
- WebDAV import via `requests` + ElementTree XML parsing
- PDF generation via `fpdf2`
