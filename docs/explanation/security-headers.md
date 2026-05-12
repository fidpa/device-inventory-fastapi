# Security Headers

Every response from the application carries the following headers, set by `SecurityHeadersMiddleware` in `src/app.py`:

```python
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; ...
```

This page explains what each does and why these specific values were chosen.

## `X-Frame-Options: DENY`

Prevents the page from being rendered inside any `<iframe>`, blocking click-jacking attacks.

We use `DENY` rather than `SAMEORIGIN` because the application is never legitimately framed — it has no embed-friendly views. If you ever need to embed it (e.g. as part of a larger admin dashboard), switch to `SAMEORIGIN` and verify the parent context is trusted.

## `X-Content-Type-Options: nosniff`

Tells the browser **not** to guess the content type of a response. Without this, IE and old Chrome versions would happily interpret a JSON response as HTML if it contained an `<html>` tag — which is a path to stored XSS.

Modern browsers default to safer behaviour, but the header costs nothing and protects users on outdated browsers.

## `Referrer-Policy: strict-origin-when-cross-origin`

Controls what the browser puts in the `Referer` header when navigating away from the app:

- Same-origin navigation: full URL (the default).
- Cross-origin to **HTTPS** target: only the origin (e.g. `https://inventory.example.com`).
- Cross-origin to **HTTP** target: no referrer at all.

This balances usability (analytics on outbound links still see the origin) with privacy (no leakage of internal URLs like `/device/42`).

## `Content-Security-Policy`

The CSP defines what resources the browser is allowed to load:

```
default-src 'self';
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com;
script-src 'self' 'unsafe-inline';
img-src 'self' data:;
connect-src 'self';
```

Per directive:

### `default-src 'self'`

Anything not explicitly overridden can only come from the same origin. This is the strict baseline.

### `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com`

`'unsafe-inline'` is regrettable — it allows inline `style=""` attributes and `<style>` blocks, which the templates use for some dynamic styling. Replacing them with hash-based or nonce-based CSP would require a broader refactor. The Google Fonts URL is allow-listed because the templates load `Inter` from there.

### `font-src 'self' https://fonts.gstatic.com`

Where actual font files are loaded from (`fonts.googleapis.com` returns CSS, `fonts.gstatic.com` serves the WOFF2 files).

### `script-src 'self' 'unsafe-inline'`

Same caveat as `style-src`: the templates use small inline `<script>` blocks for per-page initialization (e.g. to pass server data into JavaScript). Migrating to external scripts + `data-*` attributes is on the roadmap; until then, `'unsafe-inline'` stays.

> ⚠️ `'unsafe-inline'` is the single biggest concession in the CSP. If you customize the templates and want a hardened CSP, replace inline scripts with:
> ```html
> <script id="page-data" type="application/json">{"device_id": 42}</script>
> ```
> and read the JSON from the script tag in your external `.js` file.

### `img-src 'self' data:`

Templates use `data:` URIs for inlined SVG icons. If you'd rather load icons from external files, drop `data:`.

### `connect-src 'self'`

`fetch()` / `XMLHttpRequest` / WebSocket connections are limited to the same origin. The app makes no cross-origin API calls.

## What's *not* set

### `Strict-Transport-Security`

HSTS is set at the **nginx level**, not in the app. The reverse proxy is the right place for it because:

- HSTS only makes sense over HTTPS, and TLS termination is at nginx.
- nginx can apply HSTS to all sites uniformly.
- The app has no idea whether it's being served over HTTPS or HTTP (which is correct — that's nginx's job).

In your nginx config:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### `Permissions-Policy`

(Formerly `Feature-Policy`.) The app doesn't use any sensors / camera / microphone / payment APIs, so there's nothing meaningful to deny. If you add such features and want to restrict them on hostile sites, add this header.

### `X-XSS-Protection`

Deprecated in modern browsers (replaced by CSP). Setting it has no effect in current Chrome/Firefox; older versions had bugs that made `X-XSS-Protection: 1; mode=block` *enable* exploits. Don't set it.

## How to verify

Test the headers from outside the application:

```bash
curl -I https://inventory.example.com/login
# Look for the headers in the response
```

Or use online scanners like [securityheaders.com](https://securityheaders.com/). The current configuration scores **A** (with `'unsafe-inline'` being the only thing standing between us and **A+**).

## Tightening the CSP

When you've verified that no inline styles / scripts are needed:

```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; "        # removed 'unsafe-inline'
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; "                                     # removed 'unsafe-inline'
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "                                     # block <embed>, <object>
    "base-uri 'self'; "                                       # prevent <base> hijack
    "form-action 'self';"                                     # restrict form submissions
)
```

Test thoroughly afterwards — any remaining inline handler will silently break.
