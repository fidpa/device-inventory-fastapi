# API Endpoints

The application exposes ~35 HTTP endpoints. They split into three groups:

- **HTML pages** — Jinja2-rendered, return `text/html`
- **JSON API** — return `application/json`, used by the in-page JavaScript
- **Exports** — return `application/pdf` or `text/csv`

All routes (except `/login` and `/health`) require a valid `inventory_auth` cookie.

## Auth

| Method | Path | Returns | Description |
|--------|------|---------|-------------|
| `GET` | `/login` | HTML | Login form |
| `POST` | `/login` | Redirect | Verify password, set session cookie |
| `GET` | `/logout` | Redirect | Clear session cookie |

## Pages

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Device list with search and pagination |
| `GET` | `/device/{id}` | Device detail / edit page |
| `GET` | `/dashboard` | Aggregated statistics |
| `GET` | `/vpn` | VPN number assignments |
| `GET` | `/printers` | Printer list (latest scan per printer) |
| `GET` | `/printer/{scan_id}` | Single printer-scan detail |
| `GET` | `/services` | IT services list |
| `GET` | `/ctr` | Container/VM hosts and VMs |
| `GET` | `/import/log` | Import history |

## Device API

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/import` | — | Trigger an immediate import from WebDAV |
| `PATCH` | `/api/device/{id}` | JSON | Update status, inventory_no, vpn, notes, accessories |
| `DELETE` | `/api/device/{id}` | — | Delete from DB and (best-effort) WebDAV |

## Printer API

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/import/printers` | — | Trigger printer import from WebDAV |
| `DELETE` | `/api/printer-scan/{id}` | — | Delete a single printer scan entry |

## CTR (Containers / VMs) API

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/ctr/hosts` | JSON | Create a physical host |
| `PATCH` | `/api/ctr/host/{id}` | JSON | Update a host |
| `DELETE` | `/api/ctr/host/{id}` | — | Delete a host (and cascade-delete VMs) |
| `POST` | `/api/ctr/host/{id}/vms` | JSON | Create a VM under a host |
| `PATCH` | `/api/ctr/vm/{id}` | JSON | Update a VM |
| `DELETE` | `/api/ctr/vm/{id}` | — | Delete a VM |

## Services API

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/services` | JSON | Create a service entry |
| `PATCH` | `/api/service/{id}` | JSON | Update a service |
| `DELETE` | `/api/service/{id}` | — | Delete a service |

## Exports

| Method | Path | Returns | Description |
|--------|------|---------|-------------|
| `GET` | `/export/pdf` | PDF | Devices report (filtered) |
| `GET` | `/export/csv` | CSV | Devices CSV (filtered) |
| `GET` | `/export/services/pdf` | PDF | Services report |
| `GET` | `/export/ctr/pdf` | PDF | CTR servers and VMs |
| `GET` | `/export/printers/csv` | CSV | Printers list |

## Health

| Method | Path | Returns | Description |
|--------|------|---------|-------------|
| `GET` | `/health` | `text/plain` | Returns `OK` (no auth required) |

## Common response codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `302` | Redirect (e.g. unauthenticated → `/login`) |
| `400` | Validation error (bad input) |
| `401` | Authentication required |
| `404` | Resource not found |
| `429` | Rate limit hit (login) |
| `500` | Server error (logged to systemd journal) |

## Authentication header

Cookies are the only supported auth mechanism. There is no API token / Bearer header. If you need machine-to-machine access, post to `/login` first and reuse the returned `inventory_auth` cookie:

```bash
COOKIE=$(curl -c - -X POST -d "password=$PASSWORD" \
         "https://inventory.example.com/login" | \
         grep inventory_auth | awk '{print $7}')

curl -b "inventory_auth=$COOKIE" \
     "https://inventory.example.com/api/import" \
     -X POST
```
