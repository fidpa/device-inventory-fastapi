# Documentation

Documentation is organized following the [DIATAXIS](https://diataxis.fr/) framework — four distinct kinds of documentation that serve different needs:

| Section | When to read |
|---------|--------------|
| 📖 [**Tutorial**](tutorial/) | First time setting up the project — start here |
| 🔧 [**How-to guides**](how-to/) | You know what you want to do; you need a recipe |
| 📚 [**Reference**](reference/) | You need exact technical detail (API, schema, config) |
| 💡 [**Explanation**](explanation/) | You want to understand the design and trade-offs |

## Tutorials

- [Quick Start](tutorial/01-quickstart.md) — first-time setup walk-through (local development)

## How-to Guides

- [Deploy with systemd + nginx](how-to/deploy-systemd.md) — production deployment recipe
- [Configure WebDAV](how-to/configure-webdav.md) — point the importer at any WebDAV server
- [Add SNMP printer discovery](how-to/add-printer-discovery.md) — configure printer collection
- [Customize the PDF export](how-to/customize-pdf-export.md) — tweak fpdf2 layout and styling
- [Build the macOS .app bundle](how-to/build-macos-tool.md) — sign and notarize the collector
- [Build the Windows distribution](how-to/build-windows-tool.md) — package PowerShell collector

## Reference

- [Architecture](reference/architecture.md) — components and data flow
- [API endpoints](reference/api-endpoints.md) — full HTTP API surface
- [Database schema](reference/database-schema.md) — SQLite tables and relations
- [Environment variables](reference/env-vars.md) — `.env` reference
- [CLI tools](reference/cli-tools.md) — `import_sysinfo.py` / `import_printers.py`

## Explanation

- [Why a single-file FastAPI app](explanation/why-fastapi-monolith.md)
- [Authentication design](explanation/auth-design.md) — HMAC + bcrypt + rate limiting
- [Security headers](explanation/security-headers.md) — CSP, X-Frame-Options, Referrer-Policy
- [Data collection model](explanation/data-collection-model.md) — sysinfo → WebDAV → SQLite pipeline
