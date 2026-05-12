# Security Policy

## Supported Versions

Only the latest minor release receives security updates. Older versions are not patched.

| Version | Supported |
|---------|-----------|
| 1.x (latest) | ✅ |
| < 1.0 | ❌ |

## Reporting a Vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Report vulnerabilities privately via one of:

1. **GitHub Security Advisories** (preferred): use the "Report a vulnerability" button on the repository's Security tab.

Include in your report:

- A clear description of the vulnerability and its impact.
- Step-by-step reproduction instructions (smallest example that triggers the issue).
- Affected version(s) and configuration.
- Your suggested fix, if any.
- Whether you'd like to be credited in the advisory.

## Response Timeline

| Phase | Target |
|-------|--------|
| Acknowledgement | within 48 hours |
| Initial assessment | within 7 days |
| Fix availability (severity-dependent) | 14–60 days |
| Public disclosure | coordinated with reporter |

We will keep you informed at each stage.

## Scope

### In scope

- This FastAPI application (`src/app.py`)
- Bundled scripts (`scripts/`, `setup/`)
- Sysinfo collectors (`sysinfo/`)
- Authentication, session handling, security headers, rate limiting
- SQL injection, XSS, CSRF, path traversal in our code

### Out of scope

- Vulnerabilities in upstream dependencies (FastAPI, SQLite, bcrypt, requests, fpdf2). Report those to their maintainers.
- Misconfigurations of the deployment environment (nginx, systemd, OS-level firewalls).
- Issues that require physical access to the server.
- Social engineering attacks.

## Security Best Practices for Operators

When deploying this application, please:

1. **Generate a strong `AUTH_SECRET`** (32+ random bytes; the helper command in `.env.example` produces 64 hex chars).
2. **Use a dedicated WebDAV app password**, never the operator's main login password.
3. **Run behind HTTPS only** — terminate TLS at nginx (Let's Encrypt is fine).
4. **Restrict network exposure**: bind uvicorn to `127.0.0.1` and let nginx be the only listener on a public port.
5. **Rotate `AUTH_SECRET` if a session leak is suspected** — this invalidates all existing sessions.
6. **Keep Python and dependencies updated**: `pip install -U -r requirements.txt` regularly; review `CHANGELOG.md` of each upgrade.
7. **Back up the SQLite database** with `.backup` (online backup) or by copying the `.db` while the WAL is checkpointed.
8. **Review logs regularly** — repeated 401s from the same IP indicate brute-force attempts (rate limiting catches the worst, but persistent attackers should be banned at the firewall).

## Disclosure Policy

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). Once a fix is available:

- We publish a GitHub Security Advisory describing the issue.
- We credit the reporter (with permission).
- We document the fix in `CHANGELOG.md` under a `### Security` heading.

Thank you for helping keep this project safe.
