# Authentication Design

The application uses a deliberately simple authentication model:

- **One operator login** (no user accounts in the database).
- **bcrypt** for password verification.
- **HMAC-SHA256** signed cookies for session state (no server-side session store).
- **In-memory rate limiting** for login attempts.

This page explains why each piece looks the way it does.

## One login, not a user table

The application targets a single-tenant, single-operator deployment. Adding a user table would mean:

- Account creation / deletion endpoints.
- Password reset flow (with email).
- Per-user permission scopes.
- A "first admin" bootstrap problem.

For 50–200 devices and one IT person, this is over-engineering. The login is configured via `AUTH_PASSWORD_HASH` in `.env`. If you need multi-user support, that's the right time to fork the project and add a real auth system.

## bcrypt, not argon2

bcrypt is older but **is supported by every Python deployment without compilation**. The `bcrypt` package on PyPI is precompiled for all major platforms. argon2 is theoretically stronger but adds installation friction (`argon2-cffi` requires libargon2 development headers in some environments).

Cost factor 12 is the default — about 250 ms per verification on commodity hardware. Slow enough to make brute force impractical, fast enough that login feels instant.

```python
import bcrypt
hash = bcrypt.hashpw(b"password", bcrypt.gensalt(rounds=12))
ok = bcrypt.checkpw(b"password", hash)
```

## HMAC-signed cookies, not server sessions

After successful login, the server issues a cookie containing:

```
base64(unix_timestamp.hmac_sha256(secret, unix_timestamp))
```

To verify the cookie:

1. Decode base64.
2. Split on `.`.
3. Recompute HMAC of the timestamp.
4. Use `hmac.compare_digest()` (constant-time comparison — important to prevent timing attacks).
5. Reject if the timestamp is older than `COOKIE_MAX_AGE`.

This means **the server stores no session state**. There's no Redis session store, no session table, no garbage collection of expired entries. The cookie *is* the session.

### Why not JWT?

JWT is the same idea (signed token in a cookie or header) with more features: claims, audience, expiry, algorithm negotiation. For one operator with one role, none of those features add value, and the JWT spec has had enough security footguns (alg=none, RS256/HS256 confusion) that rolling our own is genuinely simpler.

The token here has exactly one claim — a timestamp — and exactly one supported algorithm — HMAC-SHA256. There's no way to confuse it.

### Cookie attributes

```python
response.set_cookie(
    key="inventory_auth",
    value=token,
    max_age=COOKIE_MAX_AGE,
    httponly=True,        # Not accessible to JavaScript
    secure=True,          # HTTPS only
    samesite="lax",       # CSRF protection
)
```

The combination of `HttpOnly` + `Secure` + `SameSite=Lax` is the modern baseline for session cookies. It defeats:

- **XSS-based session theft** — JS can't read `HttpOnly` cookies.
- **Cleartext snooping** — `Secure` prevents the cookie from being sent over plain HTTP.
- **CSRF on state-changing requests** — `SameSite=Lax` blocks cross-origin POSTs from sending the cookie.

There's no separate CSRF token because `SameSite=Lax` is now considered sufficient for typical CRUD apps. If you serve the app from multiple origins or expect to be embedded in iframes, switch `SameSite` to `Strict` and add a CSRF token.

## Rate limiting

A simple per-IP counter:

```python
_RL_MAX = 5
_RL_WINDOW = 60  # seconds

# Pseudocode
attempts = [t for t in attempts_for_ip(ip) if now - t < _RL_WINDOW]
if len(attempts) >= _RL_MAX:
    return 429 Too Many Requests
```

The state is **in-memory only** — restarting the application clears it. This is acceptable because:

- Login is rare (< 10 attempts per day in normal operation).
- An attacker who can restart the application has bigger problems than rate limiting.
- For sustained brute force the response is to ban the IP at the firewall (`iptables` / `ufw`), not to make the rate limiter persistent.

### Why not Redis-backed?

Redis would make the rate limiter survive restarts and work across multiple uvicorn workers. Both useful in larger deployments. For single-worker single-server, in-memory is enough — and Redis is one more daemon to monitor.

### IP detection

`request.client.host` returns the IP that uvicorn sees. **Behind nginx**, that's `127.0.0.1`. To rate-limit by the real client IP, you need:

```python
forwarded_for = request.headers.get("x-forwarded-for", "")
ip = forwarded_for.split(",")[0].strip() or request.client.host
```

The current code does not do this — adding it is on the roadmap. For now the rate limit applies per-uvicorn-worker rather than per-real-IP, which is suboptimal but tolerable.

## Threat model

The auth design defends against:

- Credential stuffing (slow bcrypt + rate limit)
- Cookie theft via XSS (HttpOnly cookies + CSP)
- Session fixation (no server session, every login generates a fresh token)
- Replay attacks beyond cookie lifetime (timestamp check + HMAC)
- CSRF on state-changing requests (SameSite=Lax)

The auth design does **not** defend against:

- A compromised server (anyone with `AUTH_SECRET` can mint valid cookies).
- A compromised operator account (no MFA, no anomaly detection).
- DoS by repeated login attempts from many IPs (the in-memory rate limiter is per-IP, so a botnet bypasses it).

For higher-security deployments, layer additional controls at the network and OS level: fail2ban, WAF, VPN-only access, MFA via reverse-proxy auth.
