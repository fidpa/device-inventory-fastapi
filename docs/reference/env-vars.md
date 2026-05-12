# Environment Variables

All configuration is read from a `.env` file at the project root (loaded via `python-dotenv` at startup).

## Required

### Authentication

| Variable | Type | Description |
|----------|------|-------------|
| `AUTH_PASSWORD_HASH` | string | bcrypt hash of the login password. Format `$2b$12$...`. |
| `AUTH_SECRET` | string | HMAC key for session cookie signing. **Minimum 32 bytes** (64 hex chars). |

#### Generating

```bash
# Bcrypt password hash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt(12)).decode())"

# HMAC secret (64 hex chars = 32 bytes)
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### WebDAV

| Variable | Type | Description |
|----------|------|-------------|
| `NEXTCLOUD_URL` | URL | Base URL of the WebDAV server (no trailing slash) |
| `NEXTCLOUD_USER` | string | Account name (used in HTTP Basic auth) |
| `NEXTCLOUD_PASSWORD` | string | App-specific password (NOT the login password) |
| `NEXTCLOUD_PATH` | path | Inbox path on the WebDAV server, with leading `/` |

The variable names are historical — they work with any WebDAV-compatible server.

## Behaviour notes

### Cookie lifetime

The session cookie's `Max-Age` is hardcoded in `src/app.py` at `COOKIE_MAX_AGE = 90 * 24 * 3600` (90 days). Change the source if you need a different lifetime; there's no environment variable for it.

### Rate limiting

The login rate limiter is hardcoded:

```python
_RL_MAX = 5        # max attempts
_RL_WINDOW = 60    # window in seconds
```

State is in-memory and reset on application restart.

### Database location

`DB_PATH` is derived from the project root: `<project>/db/devices.db`. Override via `APP_DIR` is not currently supported — symlink the `db/` directory if you need to relocate it (e.g. to a separate disk).

## Operational tips

- **`.env` permissions**: must be `0600` and owned by the application user. The setup script does this; if you create the file by hand, run `chmod 600 .env` afterwards.
- **Secret rotation**: rotating `AUTH_SECRET` invalidates all existing sessions. Useful in case of suspected compromise; harmless otherwise — users just have to log in again.
- **WebDAV password rotation**: revoke the old app password in your WebDAV provider's UI, generate a new one, update `.env`, restart `device-inventory.service`.

## Example `.env`

```ini
NEXTCLOUD_URL=https://cloud.example.com
NEXTCLOUD_USER=sysinfo
NEXTCLOUD_PASSWORD=AbCd-EfGh-IjKl-MnOp
NEXTCLOUD_PATH=/remote.php/dav/files/sysinfo/inbox

AUTH_PASSWORD_HASH=$2b$12$abcdefghijklmnopqrstuv.OQQHhh1234567890ABCDEFGHIJKLM
AUTH_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

A copy with placeholder values is checked in as [`.env.example`](../../.env.example).
